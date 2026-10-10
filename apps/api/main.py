"""AsBoljam API. All operational queries are organization and branch scoped."""
import atexit
import hashlib
import json
import os
import secrets
import time
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Literal
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select, text, update
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import object_session
from .accounts import CredentialError, change_password, lock_user, revoke_user_access
from .config import load_settings
from .db import AuthSession, Audit, Forecast, Idempotency, ImportBatch, Job, LoginAttempt, Organization, Plan, Record, RefreshToken, User, make_engine, migrate, sessions
from .importing import SCHEMAS, insert_rows, parse_csv, rows_for, safe_csv, validate_rows
from .import_service import ImportProblem, batch_view, commit_import, get_batch, list_batches, preview_import
from .lineage import capture_lineage, input_freshness, input_provenance
from .security import password_hash, token_hash, verify_password
from .stock import StockError
from .stock_api import register_stock_routes
from .stock_dependencies import prepare_procurement_stock
from .tenants import organization_active, organization_json
from .data_policy import (DataPolicyError, ensure_rows, execution_context, metadata,
                          policy_context, validate_execution_context, workspace_context)

SCENARIO = '2026-01-01'
META = {'data_origin': 'SYNTHETIC', 'scenario_date': SCENARIO}

def uid():
    return uuid.uuid4().hex

def fail(code, message, status=400):
    raise HTTPException(status, {'code': code, 'message': message})

class StrictModel(BaseModel):
    model_config = ConfigDict(extra='forbid')
class Login(StrictModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=1024)
class Refresh(StrictModel):
    refresh_token: str = Field(min_length=20, max_length=256)
class PasswordChange(StrictModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=12, max_length=1024)
class ImportSource(StrictModel):
    source_id: str = Field(default='manual_csv', pattern=r'^[A-Za-z0-9_.:-]{1,64}$')
    mapping_version: str = Field(default='canonical-v1', pattern=r'^[A-Za-z0-9_.:-]{1,64}$')
    declared_original_sha256: str | None = Field(default=None, pattern=r'^[a-fA-F0-9]{64}$')
class ImportInput(StrictModel):
    kind: str = Field(max_length=32)
    csv_text: str
    mode: Literal['append','correction'] = 'append'
    reason: str | None = Field(default=None, max_length=1000)
    corrects_batch_id: str | None = Field(default=None, pattern=r'^[A-Za-z0-9_-]{1,64}$')
    source: ImportSource | None = None
class ForecastInput(StrictModel):
    branch_id: str
    origin: date | None = None
    model: Literal['seasonal_naive_7','rolling_mean_28','hist_gradient_boosting'] = 'seasonal_naive_7'
class ProcurementInput(StrictModel):
    branch_id: str
    forecast_id: str
    budget: Decimal = Field(ge=0, le=1000000000, max_digits=14, decimal_places=2)
    strategy: Literal['point','p50','p90_stress'] = 'point'
class ApprovalInput(StrictModel):
    expected_version: int = Field(ge=1)
    reason: str = Field(min_length=3, max_length=1000)
    acknowledge_shortage: bool = False
class UserInput(StrictModel):
    email: str = Field(min_length=3,max_length=255)
    password: str = Field(min_length=12,max_length=1024)
    role: Literal['admin','manager','analyst','warehouse']
    branch_ids: list[str] = Field(default_factory=list)
class UserAccess(StrictModel):
    role: Literal['admin','manager','analyst','warehouse']
    branch_ids: list[str] = Field(default_factory=list)
    active: bool = True
class QueuedResponse(BaseModel):
    run_id: str
    status: str = 'queued'
class RunResponse(BaseModel):
    id: str
    run_id: str
    kind: str
    status: str
    result_id: str | None
    error: str | None
    created_at: str
    started_at: float | None = Field(description='Unix seconds; start of the current worker claim, not percent complete.')
    heartbeat_at: float | None = Field(description='Unix seconds; last worker lease renewal, not proof of calculation progress.')
    finished_at: str | None
    observed_at: float = Field(description='Server Unix seconds when this status was read; use with heartbeat_at to avoid client clock skew.')
    data_origin: str | None
    usage_mode: str | None
    scenario_date: str | None
class RunCollection(BaseModel):
    items: list[RunResponse]
    total: int
    next_cursor: str | None
class CollectionResponse(BaseModel):
    items: list[dict]
    total: int
    next_cursor: str | None
    data_origin: str | None = None
    scenario_date: str | None = None
    usage_mode: str | None = None
class OrganizationView(BaseModel):
    id: str
    name: str | None
    timezone: str | None
    currency: str
    status: Literal['active','suspended']
    data_policy: Literal['synthetic_only','real_only','unconfigured']
    provenance: str
class OnboardingView(BaseModel):
    branch_count: int
    can_import_branches: bool
    data_policy: Literal['synthetic_only','real_only','unconfigured']
class SettingsResponse(BaseModel):
    organization: OrganizationView
    timezone: str | None
    currency: str
    onboarding: OnboardingView
    language: str = 'kk-KZ'
    read_only: bool = True
    user: dict
    forecast_horizon_days: int = 1
    data_origin: str | None = None
    scenario_date: str | None = None
    usage_mode: str | None = None
    data_context: dict


def user_json(user):
    return {key: getattr(user,key) for key in ('id','email','role','organization_id','branch_ids','active')}
def result_metadata(result):
    origin = result.get('data_origin')
    context = result.get('execution_context') or {}
    return {'data_origin': origin, 'usage_mode': context.get('usage_mode', 'DEMO' if origin == 'SYNTHETIC' else None),
            'scenario_date': SCENARIO if origin == 'SYNTHETIC' else None}
def plan_json(plan, freshness_cache=None):
    lineage=plan.result.get('input_lineage')
    result={key:value for key,value in plan.result.items() if key!='input_lineage'}
    return {**result, **result_metadata(result), 'id':plan.id,'run_id':plan.id,'branch_id':plan.branch_id,'forecast_id':plan.forecast_id,'version':plan.version,'status':plan.status,'created_at':plan.created_at,
            'input_freshness':input_freshness(object_session(plan),plan.organization_id,lineage,state_cache=freshness_cache),
            'input_provenance':input_provenance(plan.organization_id,lineage)}
def forecast_json(forecast, freshness_cache=None):
    lineage=forecast.result.get('input_lineage')
    result={key:value for key,value in forecast.result.items() if key!='input_lineage'}
    return {**result, **result_metadata(result), 'id':forecast.id,'run_id':forecast.id,'branch_id':forecast.branch_id,'created_at':forecast.created_at,
            'input_freshness':input_freshness(object_session(forecast),forecast.organization_id,lineage,state_cache=freshness_cache),
            'input_provenance':input_provenance(forecast.organization_id,lineage)}

def create_app(database_url=None):
    runtime_settings = load_settings(database_url)
    app = FastAPI(title='AsBoljam', version='1.1.0', description='Scoped catering operations; explicit demo or operator-configured source; one-day forecasts; internal approval only.')
    engine = make_engine(runtime_settings.database_url)
    migrate(engine)
    atexit.register(engine.dispose)
    app.state.engine = engine
    app.state.sessions = sessions(engine)
    app.state.settings = runtime_settings
    allowed_origins = list(runtime_settings.allowed_origins)
    secure = runtime_settings.cookie_secure
    app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_credentials=True, allow_methods=['GET','POST','PATCH'], allow_headers=['Content-Type','X-CSRF-Token','Idempotency-Key','Authorization'])

    @app.exception_handler(ImportProblem)
    @app.exception_handler(DataPolicyError)
    @app.exception_handler(StockError)
    async def import_problem(request:Request,exc:ImportProblem):
        return JSONResponse(status_code=exc.status,content={'detail':{'code':exc.code,'message':exc.message}})
    @app.exception_handler(RequestValidationError)
    async def safe_credential_validation(request, exc):
        if request.url.path == '/api/v1/account/password':
            # The normal Pydantic response includes input values. Passwords stay private.
            return JSONResponse({'detail': {'code': 'PASSWORD_INVALID',
                'message': 'Құпиясөз өрістерін тексеріңіз: қазіргі 1–1024, жаңа 12–1024 таңба.'}}, 422)
        if request.url.path in {'/api/v1/session/login','/api/v1/auth/token','/api/v1/auth/refresh','/api/v1/users'}:
            return JSONResponse({'detail': {'code': 'VALIDATION_ERROR',
                'message': 'Сұрау өрістерін тексеріңіз.'}}, 422)
        return await request_validation_exception_handler(request, exc)

    @app.middleware('http')
    async def protection(request, call_next):
        response = None
        if request.method in {'POST','PATCH','PUT','DELETE'}:
            length = request.headers.get('content-length')
            if length is not None:
                if not length.isascii() or not length.isdecimal() or len(length)>20:
                    response = JSONResponse({'detail':{'code':'INVALID_CONTENT_LENGTH','message':'Сұрау өлшемі жарамсыз.'}},400)
                elif int(length) > 22 * 1024 * 1024:
                    response = JSONResponse({'detail':{'code':'FILE_TOO_LARGE','message':'Сұрау өлшемі шектен асты.'}},413)
        if response is None:
            response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Cache-Control'] = 'no-store'
        if runtime_settings.environment == 'production':
            response.headers['Strict-Transport-Security'] = 'max-age=31536000'
        return response

    def get_db():
        with app.state.sessions() as db:
            yield db
    def origin_check(request):
        if request.headers.get('origin') not in allowed_origins:
            fail('ORIGIN_FORBIDDEN','Сұрау көзіне рұқсат жоқ.',403)
    def current(request: Request, db=Depends(get_db)):
        bearer = request.headers.get('authorization','')
        native = bearer.startswith('Bearer ')
        token = bearer[7:] if native else request.cookies.get('asboljam_session','')
        auth = db.scalar(select(AuthSession).where(AuthSession.token_hash==token_hash(token))) if token else None
        if not auth or auth.revoked or auth.expires_at < time.time() or auth.kind != ('native' if native else 'web'):
            fail('AUTH_REQUIRED','Жүйеге кіріңіз.',401)
        user = db.get(User, auth.user_id)
        if not user or not user.active or not organization_active(db,user.organization_id):
            fail('AUTH_REQUIRED','Есептік жазба қолжетімсіз.',401)
        if request.method not in {'GET','HEAD','OPTIONS'} and not native:
            origin_check(request)
            if not secrets.compare_digest(request.headers.get('x-csrf-token',''), auth.csrf_token):
                fail('CSRF_INVALID','Сессияны жаңартып, қайталаңыз.',403)
        if request.method not in {'GET','HEAD','OPTIONS'}:
            identity='mutation:'+user.id
            count=db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.identity==identity,LoginAttempt.timestamp>time.time()-60))
            if count>=60: fail('RATE_LIMITED','Too many changes; retry after one minute.',429)
            db.add(LoginAttempt(id=uid(),identity=identity,timestamp=time.time()))
            db.commit()
            # The rate-limit commit released locks. Revalidate and hold tenant access
            # through the actual mutation so suspension cannot interleave side effects.
            user=lock_user(db,user.id,user.organization_id)
            auth=db.get(AuthSession,auth.id,populate_existing=True)
            if (not user or not user.active or not auth or auth.revoked
                    or auth.expires_at<time.time() or not organization_active(db,user.organization_id)):
                fail('AUTH_REQUIRED','Қайта кіріңіз.',401)
        organization=db.get(Organization,user.organization_id,populate_existing=True)
        allowed_setup = (request.url.path in {'/api/v1/settings','/api/v1/audit',
            '/api/v1/session/me','/api/v1/session/logout','/api/v1/account/password','/api/v1/users'}
            or request.url.path.startswith('/api/v1/users/')
            or request.url.path.startswith('/api/v1/imports/template/'))
        if organization.data_policy not in {'synthetic_only','real_only'} and not allowed_setup:
            fail('TENANT_DATA_POLICY_REQUIRED','Деректер режимін әкімші баптауы керек.',403)
        if organization.data_policy == 'real_only':
            policy_context(db, organization.id)
            if native and not allowed_setup:
                fail('NATIVE_REAL_UNSUPPORTED','REAL деректері үшін web нұсқасын пайдаланыңыз.',403)
        request.state.organization=organization
        request.state.auth = auth
        return user
    def roles(user, *allowed):
        if user.role not in allowed:
            fail('ROLE_FORBIDDEN','Бұл әрекетке рұқсат жоқ.',403)
    def branch_access(db, user, branch):
        if branch not in user.branch_ids:
            fail('BRANCH_FORBIDDEN','Бөлімшеге рұқсат жоқ.',403)
        if not any(r['branch_id']==branch for r in rows_for(db,user.organization_id,'branches')):
            fail('BRANCH_NOT_FOUND','Бөлімше табылмады.',404)
    def audit(db,user,action,entity,branch=None,details=None):
        db.add(Audit(id=uid(),organization_id=user.organization_id,branch_id=branch,actor_id=user.id,action=action,entity_id=entity,details=details or {}))
    register_stock_routes(app, current=current, get_db=get_db, roles=roles, branch_access=branch_access)
    def scoped(db,model,user,entity_id):
        row = db.get(model,entity_id)
        if not row or row.organization_id != user.organization_id or row.branch_id not in user.branch_ids:
            fail('NOT_FOUND','Жазба табылмады.',404)
        return row
    def authenticate(data, request, db):
        identity = hashlib.sha256((data.email.lower()+'|'+(request.client.host if request.client else 'unknown')).encode()).hexdigest()
        count = db.scalar(select(func.count()).select_from(LoginAttempt).where(LoginAttempt.identity==identity,LoginAttempt.timestamp>time.time()-900))
        if count >= 10:
            fail('RATE_LIMITED','Кіру әрекеті тым көп. 15 минуттан кейін қайталаңыз.',429)
        db.add(LoginAttempt(id=uid(),identity=identity,timestamp=time.time()))
        db.commit()
        user = db.scalar(select(User).where(User.email==data.email.lower()))
        if user:
            # Hold until the session/token creation commits; reset cannot interleave.
            user = lock_user(db,user.id)
        if (not user or not verify_password(data.password,user.password_hash) or not user.active
                or not organization_active(db,user.organization_id)):
            fail('INVALID_CREDENTIALS','Пошта немесе құпиясөз қате.',401)
        return user
    def native_tokens(db,user,family=None):
        access,refresh = secrets.token_urlsafe(48),secrets.token_urlsafe(48)
        family = family or uid()
        db.add(AuthSession(id=uid(),user_id=user.id,token_hash=token_hash(access),csrf_token='',kind='native',family_id=family,expires_at=time.time()+900))
        db.add(RefreshToken(token_hash=token_hash(refresh),user_id=user.id,family_id=family,expires_at=time.time()+30*86400))
        return {'access_token':access,'refresh_token':refresh,'token_type':'Bearer','expires_in':900,'user':user_json(user)}

    @app.get('/api/v1/health')
    def health():
        return {'status':'ok'}

    @app.get('/api/v1/ready', responses={503: {'description': 'Database unavailable or migration required'}})
    def ready():
        # Public probe exposes no tenant data, schema versions or connection details.
        from .migrations import VERSIONS
        try:
            with engine.connect() as connection:
                applied = tuple(connection.execute(text('SELECT version FROM schema_migrations ORDER BY version')).scalars())
            code = None if applied == VERSIONS else 'MIGRATION_REQUIRED'
        except SQLAlchemyError:
            code = 'DATABASE_UNAVAILABLE'
        return JSONResponse(status_code=503 if code else 200,
            content={'status': 'unavailable', 'code': code} if code else {'status': 'ready'},
            headers={'Cache-Control': 'no-store'})
    @app.post('/api/v1/session/login')
    def login(data: Login, request:Request,response:Response,db=Depends(get_db)):
        origin_check(request)
        user = authenticate(data,request,db)
        token,csrf = secrets.token_urlsafe(48),secrets.token_urlsafe(32)
        db.add(AuthSession(id=uid(),user_id=user.id,token_hash=token_hash(token),csrf_token=csrf,kind='web',expires_at=time.time()+8*3600))
        audit(db,user,'session.login',user.id)
        db.commit()
        response.set_cookie('asboljam_session',token,httponly=True,secure=secure,samesite='lax',max_age=8*3600,path='/api')
        return {'user':user_json(user),'csrf_token':csrf,**metadata(db,user.organization_id)}
    @app.get('/api/v1/session/me')
    def me(request:Request,user=Depends(current),db=Depends(get_db)):
        return {'user':user_json(user),'csrf_token':request.state.auth.csrf_token,**metadata(db,user.organization_id)}
    @app.post('/api/v1/account/password')
    def account_password(data:PasswordChange,request:Request,response:Response,user=Depends(current),db=Depends(get_db)):
        try:
            result=change_password(db,organization_id=user.organization_id,user_id=user.id,
                current_password=data.current_password,new_password=data.new_password,
                session_id=request.state.auth.id)
            db.commit()
        except CredentialError as exc:
            db.rollback()
            fail(exc.code,exc.message,exc.status)
        response.delete_cookie('asboljam_session',path='/api',secure=secure,httponly=True,samesite='lax')
        return result
    @app.post('/api/v1/session/logout')
    def logout(request:Request,response:Response,user=Depends(current),db=Depends(get_db)):
        request.state.auth.revoked=True
        if request.state.auth.family_id:
            db.execute(update(RefreshToken).where(RefreshToken.family_id==request.state.auth.family_id).values(revoked=True))
        db.commit()
        response.delete_cookie('asboljam_session',path='/api',secure=secure,httponly=True,samesite='lax')
        return {'status':'logged_out'}
    @app.post('/api/v1/auth/token')
    def token(data:Login,request:Request,db=Depends(get_db)):
        user=authenticate(data,request,db)
        result=native_tokens(db,user)
        audit(db,user,'native.login',user.id)
        db.commit()
        return result
    @app.post('/api/v1/auth/refresh')
    def refresh(data:Refresh,db=Depends(get_db)):
        old=db.get(RefreshToken,token_hash(data.refresh_token))
        if old:
            # All credential operations take User first, then token/session rows.
            user=lock_user(db,old.user_id)
            old=db.get(RefreshToken,token_hash(data.refresh_token),populate_existing=True)
        else:
            user=None
        if not old or old.revoked or old.expires_at<time.time():
            fail('REFRESH_INVALID','Қайта кіріңіз.',401)
        changed=db.execute(update(RefreshToken).where(RefreshToken.token_hash==old.token_hash,RefreshToken.used==False,RefreshToken.revoked==False).values(used=True)).rowcount
        if not changed:
            db.execute(update(RefreshToken).where(RefreshToken.family_id==old.family_id).values(revoked=True))
            db.execute(update(AuthSession).where(AuthSession.family_id==old.family_id).values(revoked=True))
            db.commit()
            fail('REFRESH_REUSED','Сессия қауіпсіздік үшін тоқтатылды.',401)
        if not user or not user.active or not organization_active(db,user.organization_id):
            fail('AUTH_REQUIRED','Қайта кіріңіз.',401)
        db.execute(update(AuthSession).where(AuthSession.family_id==old.family_id).values(revoked=True))
        result=native_tokens(db,user,old.family_id)
        db.commit()
        return result

    def visible_rows(db,user,kind,branch=None):
        if branch:
            branch_access(db,user,branch)
        result=rows_for(db,user.organization_id,kind,branch if kind in {'daily_sales','calendar','inventory_lots'} else None)
        ensure_rows(policy_context(db,user.organization_id),result)
        return [r for r in result if 'branch_id' not in r or r['branch_id'] in user.branch_ids and (not branch or r['branch_id']==branch)]
    def decorate(db,user,kind,rows):
        meals={r['meal_id']:r for r in rows_for(db,user.organization_id,'meals')}
        ingredients={r['ingredient_id']:r for r in rows_for(db,user.organization_id,'ingredients')}
        context=policy_context(db,user.organization_id)
        ensure_rows(context,list(meals.values())+list(ingredients.values()))
        for original in rows:
            row=dict(original)
            if row.get('meal_id') in meals:
                row['meal_name']=meals[row['meal_id']]['meal_name']
            if row.get('ingredient_id') in ingredients:
                ingredient=ingredients[row['ingredient_id']]
                row['ingredient_name']=ingredient['ingredient_name']
                row.setdefault('unit',ingredient['unit'])
                if kind=='recipes': row['yield_factor']=ingredient['yield_factor']
            if kind=='inventory_lots':
                row['expired']=row['expiry_date']<row['snapshot_date']
            if kind=='suppliers':
                row['offers']=[r for r in rows_for(db,user.organization_id,'supplier_offers') if r['supplier_id']==row['supplier_id']]
            yield row
    aliases={'sales':'daily_sales','inventory':'inventory_lots',**{k:k for k in SCHEMAS}}
    def list_endpoint(kind):
        def endpoint(branch_id:str|None=None,limit:int=Query(50,ge=1,le=200),cursor:int=Query(0,ge=0),date_from:str|None=None,date_to:str|None=None,meal_id:str|None=None,user=Depends(current),db=Depends(get_db)):
            if user.role=='warehouse' and kind not in {'inventory_lots','branches','ingredients'}:
                roles(user,'admin','manager','analyst')
            rows=visible_rows(db,user,kind,branch_id)
            if meal_id: rows=[r for r in rows if r.get('meal_id')==meal_id]
            if date_from: rows=[r for r in rows if r.get('date',r.get('snapshot_date',''))>=date_from]
            if date_to: rows=[r for r in rows if r.get('date',r.get('snapshot_date',''))<=date_to]
            rows=sorted(rows,key=lambda r:(r.get('date',r.get('snapshot_date','')),str(r.get('meal_id',''))),reverse=True)
            return {'items':list(decorate(db,user,kind,rows[cursor:cursor+limit])),'total':len(rows),'next_cursor':str(cursor+limit) if cursor+limit<len(rows) else None,**metadata(db,user.organization_id)}
        endpoint.__name__='list_'+kind
        return endpoint
    for name,kind in aliases.items():
        app.add_api_route('/api/v1/'+name,list_endpoint(kind),methods=['GET'],response_model=CollectionResponse)

    @app.get('/api/v1/dashboard')
    def dashboard(branch_id:str,inventory_date:date|None=None,user=Depends(current),db=Depends(get_db)):
        branch_access(db,user,branch_id)
        roles(user,'admin','manager','analyst')
        sales=visible_rows(db,user,'daily_sales',branch_id)
        last_date=max((r['date'] for r in sales),default=None)
        latest=[r for r in sales if r['date']==last_date]
        history=defaultdict(int)
        top=defaultdict(lambda:{'units_sold':0,'revenue':Decimal(0)})
        names={r['meal_id']:r['meal_name'] for r in rows_for(db,user.organization_id,'meals')}
        for r in sales:
            history[r['date']]+=r['units_sold']
        for r in latest:
            item=top[r['meal_id']]
            item['units_sold']+=r['units_sold'];item['revenue']+=Decimal(r['price_kzt'])*r['units_sold']
        plans=list(db.scalars(select(Plan).where(Plan.organization_id==user.organization_id,Plan.branch_id==branch_id).order_by(Plan.created_at.desc()).limit(5)))
        forecasts=list(db.scalars(select(Forecast).where(Forecast.organization_id==user.organization_id,Forecast.branch_id==branch_id).order_by(Forecast.created_at.desc()).limit(1)))
        dates=workspace_context(db,user.organization_id,branch_id)
        snapshot_date=inventory_date.isoformat() if inventory_date else dates['inventory_date']
        lots=[r for r in visible_rows(db,user,'inventory_lots',branch_id) if r['snapshot_date']==snapshot_date]
        expiry_limit=date.fromordinal(min(date.max.toordinal(),date.fromisoformat(snapshot_date).toordinal()+2)).isoformat() if snapshot_date else None
        expired_count=sum(1 for r in lots if r['expiry_date']<snapshot_date)
        expiring_count=sum(1 for r in lots if snapshot_date<=r['expiry_date']<=expiry_limit)
        warnings=[]
        if not lots:
            warnings.append({'code':'INVENTORY_UNKNOWN','count':None,'message':'Таңдалған күнге қойма кесіндісі жоқ.'})
        if expired_count:
            warnings.append({'code':'EXPIRED_LOTS','count':expired_count,'message':f'{expired_count} партияның жарамдылық мерзімі өткен.'})
        if expiring_count:
            warnings.append({'code':'EXPIRING_LOTS','count':expiring_count,'message':f'{expiring_count} партияның мерзімі екі күн ішінде аяқталады.'})
        last_plan=plans[0] if plans else None
        return {**metadata(db,user.organization_id),'branch_id':branch_id,'inventory_date':snapshot_date,'inventory_known':bool(lots),'as_of':last_date,'sold_portions':sum(r['units_sold'] for r in latest),'revenue':str(sum((Decimal(r['price_kzt'])*r['units_sold'] for r in latest),Decimal(0))),'total_shortages':last_plan.result.get('shortage_count',0) if last_plan else None,'procurement_cost':last_plan.result.get('total_cost') if last_plan else None,'history':[{'date':d,'units_sold':history[d]} for d in sorted(history)[-28:]],'top_meals':[{'meal_id':k,'meal_name':names.get(k,k),'units_sold':v['units_sold'],'revenue':str(v['revenue'])} for k,v in sorted(top.items(),key=lambda item:-item[1]['units_sold'])],'warnings':warnings,'latest_plans':[plan_json(p) for p in plans],'latest_forecast':forecast_json(forecasts[0]) if forecasts else None}

    @app.get('/api/v1/imports/template/{kind}')
    def import_template(kind:str,user=Depends(current)):
        if kind not in SCHEMAS: fail('UNSUPPORTED_KIND','Unsupported CSV kind.',400)
        roles(user,'admin','manager','analyst','warehouse')
        if user.role=='warehouse' and kind!='inventory_lots': roles(user,'admin','manager','analyst')
        if kind not in {'daily_sales','calendar','inventory_lots'}: roles(user,'admin')
        content='\ufeff'+','.join(SCHEMAS[kind].split())+'\r\n'
        return Response(content,media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="{kind}-template.csv"'})

    @app.post('/api/v1/imports/preview')
    def import_preview(data:ImportInput,user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','warehouse')
        if user.role=='warehouse' and data.kind!='inventory_lots': roles(user,'admin','manager')
        if data.kind not in SCHEMAS: fail('UNSUPPORTED_KIND','Рұқсат етілмеген файл түрі.')
        if data.kind not in {'daily_sales','calendar','inventory_lots'}: roles(user,'admin')
        result=preview_import(db,user,**data.model_dump())
        db.commit()
        return result
    @app.get('/api/v1/imports')
    def import_history(limit:int=Query(50,ge=1,le=200),cursor:int=Query(0,ge=0),user=Depends(current),db=Depends(get_db)):
        return list_batches(db,user,limit,cursor)
    @app.get('/api/v1/imports/{batch_id}')
    def import_detail(batch_id:str,user=Depends(current),db=Depends(get_db)):
        batch,evidence=get_batch(db,user,batch_id)
        return batch_view(db,user,batch,evidence)
    @app.post('/api/v1/imports/{batch_id}/commit')
    def import_commit(batch_id:str,idempotency_key:str|None=Header(None),user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','warehouse')
        try:
            result=commit_import(db,user,batch_id,idempotency_key)
            db.commit()
        except IntegrityError:
            db.rollback();fail('IMPORT_CONCURRENT_RETRY','Импортты сол кілтпен қайталаңыз.',409)
        return result

    @app.post('/api/v1/forecasts',status_code=202,response_model=QueuedResponse)
    def create_forecast(data:ForecastInput,user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager');branch_access(db,user,data.branch_id)
        context=execution_context(db,user.organization_id,data.branch_id,data.origin.isoformat() if data.origin else None)
        origin=context['origin']
        sales=rows_for(db,user.organization_id,'daily_sales',data.branch_id)
        ensure_rows(context,sales)
        sales=[r for r in sales if r['date']<=origin]
        if not sales: fail('NO_SALES','Болжамға сатылым деректері қажет.',422)
        if context['data_origin']=='REAL':
            from .engine import validate_forecast_history
            try: validate_forecast_history(sales,data.branch_id,origin)
            except ValueError: fail('DATA_HISTORY_INCOMPLETE','Әр тағамға таңдалған күнге дейін кемінде 84 үзіліссіз күн қажет. Жоқ күн нөл емес.',422)
        snapshot={'sales':sales,'meals':rows_for(db,user.organization_id,'meals'),'execution_context':context}
        ensure_rows(context,snapshot['meals'])
        snapshot['input_lineage']=capture_lineage(db,user.organization_id,[
            {'kind':'daily_sales','rows':sales,'branch_id':data.branch_id,'date_lte':origin},
            {'kind':'meals','rows':snapshot['meals']}])
        job=Job(id=uid(),organization_id=user.organization_id,branch_id=data.branch_id,actor_id=user.id,kind='forecast',payload={**data.model_dump(mode='json'),'origin':origin},snapshot=snapshot)
        db.add(job);audit(db,user,'forecast.queued',job.id,data.branch_id);db.commit()
        return {'run_id':job.id,'status':'queued'}
    def run_json(row,meta,observed_at):
        return {k:getattr(row,k) for k in ('id','kind','status','result_id','error','created_at','started_at','heartbeat_at','finished_at')} | {'run_id':row.id,'observed_at':observed_at,**meta}
    @app.get('/api/v1/runs',response_model=RunCollection)
    def run_list(response:Response,branch_id:str,kind:Literal['forecast','procurement'],
                 limit:int=Query(20,ge=1,le=50),cursor:int=Query(0,ge=0),
                 user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','analyst');branch_access(db,user,branch_id)
        scope=(Job.organization_id==user.organization_id,Job.branch_id==branch_id,Job.kind==kind)
        total=db.scalar(select(func.count()).select_from(Job).where(*scope))
        rows=list(db.scalars(select(Job).where(*scope).order_by(Job.created_at.desc(),Job.id.desc()).offset(cursor).limit(limit)))
        meta=metadata(db,user.organization_id);observed=time.time()
        response.headers['Cache-Control']='no-store'
        return {'items':[run_json(row,meta,observed) for row in rows],'total':total,
                'next_cursor':str(cursor+limit) if cursor+limit<total else None}
    @app.get('/api/v1/runs/{run_id}',response_model=RunResponse)
    def run(run_id:str,response:Response,user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','analyst')
        row=scoped(db,Job,user,run_id)
        response.headers['Cache-Control']='no-store'
        return run_json(row,metadata(db,user.organization_id),time.time())
    @app.get('/api/v1/forecasts/{forecast_id}')
    def forecast_detail(forecast_id:str,user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','analyst')
        return forecast_json(scoped(db,Forecast,user,forecast_id))
    @app.get('/api/v1/forecasts')
    def forecast_list(branch_id:str|None=None,limit:int=Query(50,ge=1,le=200),cursor:int=Query(0,ge=0),user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','analyst')
        if branch_id: branch_access(db,user,branch_id)
        scope=(Forecast.organization_id==user.organization_id,Forecast.branch_id.in_([branch_id] if branch_id else user.branch_ids))
        total=db.scalar(select(func.count()).select_from(Forecast).where(*scope))
        rows=list(db.scalars(select(Forecast).where(*scope).order_by(Forecast.created_at.desc(),Forecast.id.desc()).offset(cursor).limit(limit)))
        freshness_cache={}
        return {'items':[forecast_json(r,freshness_cache) for r in rows],'total':total,'next_cursor':str(cursor+limit) if cursor+limit<total else None,**metadata(db,user.organization_id)}
    @app.post('/api/v1/procurement',status_code=202,response_model=QueuedResponse)
    def create_procurement(data:ProcurementInput,user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager');branch_access(db,user,data.branch_id)
        forecast=scoped(db,Forecast,user,data.forecast_id)
        if forecast.branch_id!=data.branch_id: fail('BRANCH_MISMATCH','Болжам бөлімшесі сәйкес емес.',422)
        context=forecast.result.get('execution_context')
        tenant_context=policy_context(db,user.organization_id)
        if context is None:
            if tenant_context['data_origin']!='SYNTHETIC': fail('EXECUTION_CONTEXT_INVALID','Болжамның дерек көзі белгісіз. Қайта есептеңіз.',422)
            context=execution_context(db,user.organization_id,data.branch_id,forecast.result.get('origin'))
        validate_execution_context(db,user.organization_id,context)
        if forecast.result.get('data_origin')!=context['data_origin']:
            fail('DATA_ORIGIN_MISMATCH','Болжамның шығу тегі ұйымға сәйкес емес.',422)
        if data.strategy!='point' and any(r.get('p50' if data.strategy=='p50' else 'p90') is None for r in forecast.result['predictions']): fail('QUANTILES_UNAVAILABLE','Бұл модельде квантильдер жоқ.',422)
        snapshot={'forecast_result':forecast.result,'execution_context':context,**{k:rows_for(db,user.organization_id,k,data.branch_id if k=='inventory_lots' else None) for k in ['ingredients','recipes','inventory_lots','supplier_offers','suppliers']}}
        for kind in ('ingredients','recipes','inventory_lots','supplier_offers','suppliers'): ensure_rows(context,snapshot[kind])
        snapshot['inventory_lots']=[r for r in snapshot['inventory_lots'] if r['snapshot_date']==forecast.result['target_date']]
        if not snapshot['inventory_lots']: fail('STALE_INVENTORY','Қойма кесіндісі мақсат күніне сәйкес емес.',422)
        active_recipes=prepare_procurement_stock(db,user,snapshot)
        if context['data_origin']=='REAL':
            meals={row['meal_id'] for row in forecast.result['predictions']}
            required={row['ingredient_id'] for row in snapshot['recipes'] if row['meal_id'] in meals}
            present={row['ingredient_id'] for row in snapshot['inventory_lots']}
            if not required<=present: fail('INVENTORY_COVERAGE_REQUIRED','Қажетті әр ингредиенттің қалдығы көрсетілуі керек. Жоқ жазба нөл емес.',422)
        collections=[{'kind':kind,'rows':snapshot[kind],**(
            {'branch_id':data.branch_id,'snapshot_date':forecast.result['target_date']} if kind=='inventory_lots' else {})}
            for kind in ('ingredients','recipes','inventory_lots','supplier_offers','suppliers')
            if kind!='recipes' or not active_recipes]
        snapshot['input_lineage']=capture_lineage(db,user.organization_id,collections,
            inherited=forecast.result.get('input_lineage') or {},stock_dependencies=snapshot['stock_dependencies'])
        job=Job(id=uid(),organization_id=user.organization_id,branch_id=data.branch_id,actor_id=user.id,kind='procurement',payload=data.model_dump(mode='json'),snapshot=snapshot)
        db.add(job);audit(db,user,'procurement.queued',job.id,data.branch_id);db.commit()
        return {'run_id':job.id,'status':'queued'}
    @app.get('/api/v1/plans')
    def plan_list(branch_id:str|None=None,limit:int=Query(50,ge=1,le=200),cursor:int=Query(0,ge=0),user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','analyst')
        if branch_id: branch_access(db,user,branch_id)
        scope=(Plan.organization_id==user.organization_id,Plan.branch_id.in_([branch_id] if branch_id else user.branch_ids))
        total=db.scalar(select(func.count()).select_from(Plan).where(*scope))
        rows=list(db.scalars(select(Plan).where(*scope).order_by(Plan.created_at.desc(),Plan.id.desc()).offset(cursor).limit(limit)))
        freshness_cache={}
        return {'items':[plan_json(r,freshness_cache) for r in rows],'total':total,'next_cursor':str(cursor+limit) if cursor+limit<total else None,**metadata(db,user.organization_id)}
    @app.get('/api/v1/plans/{plan_id}')
    def plan_detail(plan_id:str,user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','analyst')
        return plan_json(scoped(db,Plan,user,plan_id))
    def decision(plan_id,data,key,user,db,action):
        roles(user,'admin','manager')
        if not key or len(key)>128: fail('IDEMPOTENCY_REQUIRED','Idempotency-Key тақырыбы қажет.',422)
        plan=scoped(db,Plan,user,plan_id)
        digest=hashlib.sha256(json.dumps({'plan_id':plan_id,'action':action,**data.model_dump()},sort_keys=True).encode()).hexdigest()
        old=db.scalar(select(Idempotency).where(Idempotency.organization_id==user.organization_id,Idempotency.actor_id==user.id,Idempotency.key==key))
        if old:
            if old.payload_hash!=digest: fail('IDEMPOTENCY_CONFLICT','Кілт басқа сұрауға қолданылған.',409)
            return old.response
        if plan.version!=data.expected_version or plan.status!='ready': fail('STALE_VERSION','Жоспар өзгерген немесе шешім қабылданған.',409)
        if action=='approved':
            context=plan.result.get('execution_context')
            if context is not None:
                validate_execution_context(db,user.organization_id,context)
                from .engine import validate_calculation_context
                try: validate_calculation_context(context,plan.branch_id,target_date=plan.result.get('target_date'))
                except ValueError: fail('EXECUTION_CONTEXT_INVALID','Жоспардың күні немесе дерек контексті жарамсыз.',409)
                if plan.result.get('data_origin')!=context.get('data_origin'):
                    fail('DATA_ORIGIN_MISMATCH','Жоспардың шығу тегі сәйкес емес.',409)
            elif policy_context(db,user.organization_id)['data_origin']=='REAL':
                fail('EXECUTION_CONTEXT_INVALID','Жоспардың дерек көзі белгісіз. Қайта есептеңіз.',409)
            if not plan.result.get('constraints_valid'): fail('CONSTRAINTS_INVALID','Шектеулері тексерілмеген жоспар бекітілмейді.',422)
            if plan.result.get('shortage_count',0)>0 and not data.acknowledge_shortage: fail('SHORTAGE_ACK_REQUIRED','Тапшылықты арнайы растау қажет.',422)
            freshness=input_freshness(db,user.organization_id,plan.result.get('input_lineage'))
            if freshness=='unknown': fail('INPUTS_UNVERIFIED','Дерек көзі тексерілмеген. Жоспарды қайта есептеңіз.',409)
            if freshness=='changed': fail('INPUTS_CHANGED','Кіріс деректері өзгерген. Жоспарды қайта есептеңіз.',409)
        try:
            changed=db.execute(update(Plan).where(Plan.id==plan.id,Plan.version==data.expected_version,Plan.status=='ready').values(status=action,version=data.expected_version+1)).rowcount
            if not changed:
                replay=db.scalar(select(Idempotency).where(Idempotency.organization_id==user.organization_id,Idempotency.actor_id==user.id,Idempotency.key==key))
                if replay and replay.payload_hash==digest: return replay.response
                fail('STALE_VERSION','Жоспарды басқа пайдаланушы өзгерткен.',409)
            db.refresh(plan)
            result=plan_json(plan)
            audit(db,user,'plan.'+action,plan.id,plan.branch_id,{'reason':data.reason,'acknowledge_shortage':data.acknowledge_shortage,'version':plan.version})
            db.add(Idempotency(id=uid(),organization_id=user.organization_id,actor_id=user.id,key=key,payload_hash=digest,response=result))
            db.commit()
            return result
        except IntegrityError:
            db.rollback()
            replay=db.scalar(select(Idempotency).where(Idempotency.organization_id==user.organization_id,Idempotency.actor_id==user.id,Idempotency.key==key))
            if replay and replay.payload_hash==digest: return replay.response
            fail('CONCURRENT_DECISION','Сұрауды сол кілтпен қайталаңыз.',409)
    @app.post('/api/v1/plans/{plan_id}/approve')
    def approve(plan_id:str,data:ApprovalInput,idempotency_key:str|None=Header(None),user=Depends(current),db=Depends(get_db)):
        return decision(plan_id,data,idempotency_key,user,db,'approved')
    @app.post('/api/v1/plans/{plan_id}/reject')
    def reject(plan_id:str,data:ApprovalInput,idempotency_key:str|None=Header(None),user=Depends(current),db=Depends(get_db)):
        return decision(plan_id,data,idempotency_key,user,db,'rejected')
    @app.get('/api/v1/exports/{kind}')
    def export(kind:str,branch_id:str|None=None,date_from:str|None=None,date_to:str|None=None,meal_id:str|None=None,user=Depends(current),db=Depends(get_db)):
        actual=aliases.get(kind)
        if not actual: fail('UNSUPPORTED_KIND','Экспорт түрі белгісіз.',404)
        if user.role=='warehouse' and actual not in {'inventory_lots','ingredients','branches'}: roles(user,'admin','manager','analyst')
        rows=visible_rows(db,user,actual,branch_id)
        if meal_id: rows=[r for r in rows if r.get('meal_id')==meal_id]
        if date_from: rows=[r for r in rows if r.get('date',r.get('snapshot_date',''))>=date_from]
        if date_to: rows=[r for r in rows if r.get('date',r.get('snapshot_date',''))<=date_to]
        context=policy_context(db,user.organization_id)
        filename=actual
        if context['data_origin']=='REAL':
            source=context['source']
            rows=[{**row,'usage_mode':context['usage_mode'],'source_id':source['source_id'],
                   'mapping_version':source['mapping_version'],'source_version':source['version']} for row in rows]
            filename=context['usage_mode']+'-'+actual
        return Response(safe_csv(rows),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="{filename}.csv"'})
    @app.get('/api/v1/plans/{plan_id}/export')
    def export_plan(plan_id:str,user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','analyst');plan=scoped(db,Plan,user,plan_id)
        common={'plan_id':plan.id,'status':plan.status,'version':plan.version,'target_date':plan.result.get('target_date'),**result_metadata(plan.result)}
        stock=plan.result.get('stock_evidence') or {}; recipe=plan.result.get('recipe_evidence') or {}
        common.update(stock_basis=stock.get('source'),stock_ledger_id=stock.get('ledger_id'),
            stock_fingerprint=stock.get('fingerprint'),recipe_basis=recipe.get('source'),
            recipe_fingerprint=recipe.get('fingerprint'),recipe_versions='; '.join(plan.result.get('recipe_versions') or []))
        if stock.get('count_anchor'):
            # Only plans calculated from this evidence get the new columns;
            # existing frozen exports retain their previous schema and bytes.
            anchor=stock['count_anchor']
            common.update(stock_count_anchor_id=anchor.get('id'),
                stock_count_anchor_date=anchor.get('count_date'))
        rows=[{**common,'row_type':'summary','total_cost':plan.result.get('total_cost'),'budget':plan.result.get('budget'),'shortage_count':plan.result.get('shortage_count'),'constraints_valid':plan.result.get('constraints_valid')}]
        rows += [{**common,'row_type':'requirement',**r} for r in plan.result.get('requirements',[])]
        rows += [{**common,'row_type':'purchase',**r} for r in plan.result.get('lines',[])]
        return Response(safe_csv(rows),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="plan-{plan.id}.csv"'})
    @app.get('/api/v1/audit')
    def audit_list(branch_id:str|None=None,limit:int=Query(50,ge=1,le=200),cursor:int=Query(0,ge=0),user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','analyst')
        if branch_id: branch_access(db,user,branch_id)
        query=select(Audit).where(Audit.organization_id==user.organization_id,or_(Audit.branch_id.in_([branch_id] if branch_id else user.branch_ids),Audit.branch_id==None)).order_by(Audit.created_at.desc())
        rows=list(db.scalars(query))
        return {'items':[{k:getattr(r,k) for k in ('id','branch_id','actor_id','action','entity_id','details','created_at')} for r in rows[cursor:cursor+limit]],'total':len(rows),'next_cursor':str(cursor+limit) if cursor+limit<len(rows) else None,**metadata(db,user.organization_id)}
    @app.get('/api/v1/reports')
    def reports(branch_id:str,user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','analyst');branch_access(db,user,branch_id)
        rows=list(db.scalars(select(Forecast).where(Forecast.organization_id==user.organization_id,Forecast.branch_id==branch_id).order_by(Forecast.created_at.desc()).limit(20)))
        return {'items':[{'forecast_id':r.id,'created_at':r.created_at,'metrics':r.result.get('metrics',[]),'metadata':r.result.get('metadata',{}),'origin':r.result.get('origin'),'target_date':r.result.get('target_date'),**result_metadata(r.result)} for r in rows],**metadata(db,user.organization_id)}
    @app.get('/api/v1/settings',response_model=SettingsResponse)
    def settings(request:Request,branch_id:str|None=None,user=Depends(current),db=Depends(get_db)):
        organization=request.state.organization
        if branch_id: branch_access(db,user,branch_id)
        branch_count=db.scalar(select(func.count()).select_from(Record).where(
            Record.organization_id==organization.id,Record.kind=='branches'))
        origin_metadata=metadata(db,user.organization_id)
        return {**origin_metadata,'organization':organization_json(organization),
            'data_context':workspace_context(db,organization.id,branch_id),
            'timezone':organization.timezone,'currency':organization.currency,
            'onboarding':{'branch_count':branch_count,'can_import_branches':user.role=='admin' and organization.data_policy in {'synthetic_only','real_only'},
                          'data_policy':organization.data_policy},
            'language':'kk-KZ','read_only':True,'user':user_json(user),'forecast_horizon_days':1}
    @app.get('/api/v1/users')
    def users(user=Depends(current),db=Depends(get_db)):
        roles(user,'admin')
        return {'items':[user_json(u) for u in db.scalars(select(User).where(User.organization_id==user.organization_id))],**metadata(db,user.organization_id)}
    @app.post('/api/v1/users',status_code=201)
    def create_user(data:UserInput,user=Depends(current),db=Depends(get_db)):
        roles(user,'admin')
        for branch in data.branch_ids: branch_access(db,user,branch)
        other=User(id=uid(),organization_id=user.organization_id,email=data.email.lower(),password_hash=password_hash(data.password),role=data.role,branch_ids=data.branch_ids)
        db.add(other);audit(db,user,'user.created',other.id)
        try: db.commit()
        except IntegrityError: db.rollback();fail('EMAIL_EXISTS','Пошта тіркелген.',409)
        return user_json(other)
    @app.patch('/api/v1/users/{user_id}')
    def update_user(user_id:str,data:UserAccess,user=Depends(current),db=Depends(get_db)):
        roles(user,'admin')
        if user_id==user.id: fail('SELF_ACCESS_CHANGE','Өз рұқсатыңызды өзгертуге болмайды.',422)
        for branch in data.branch_ids: branch_access(db,user,branch)
        # Serialize access revocation with worker publication on both supported databases.
        other=lock_user(db,user_id,user.organization_id)
        if not other: fail('NOT_FOUND','Пайдаланушы табылмады.',404)
        other.role,other.branch_ids,other.active=data.role,data.branch_ids,data.active
        revoke_user_access(db,other,actor_id=user.id)
        audit(db,user,'user.access_changed',other.id,details=data.model_dump());db.commit()
        return user_json(other)
    return app

app=create_app()
