"""AsBoljam API. All operational queries are organization and branch scoped."""
import atexit
import hashlib
import json
import os
import secrets
import time
import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from .db import AuthSession, Audit, Forecast, Idempotency, ImportBatch, Job, LoginAttempt, Plan, Record, RefreshToken, User, make_engine, migrate, sessions
from .importing import SCHEMAS, insert_rows, parse_csv, rows_for, safe_csv, validate_rows
from .security import password_hash, token_hash, verify_password

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
class ImportInput(StrictModel):
    kind: str = Field(max_length=32)
    csv_text: str
class ForecastInput(StrictModel):
    branch_id: str
    origin: date = date(2025,12,31)
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
    branch_ids: list[str] = Field(min_length=1)
class UserAccess(StrictModel):
    role: Literal['admin','manager','analyst','warehouse']
    branch_ids: list[str] = Field(min_length=1)
    active: bool = True
class QueuedResponse(BaseModel):
    run_id: str
    status: str = 'queued'
class CollectionResponse(BaseModel):
    items: list[dict]
    total: int
    next_cursor: str | None
    data_origin: str = 'SYNTHETIC'
    scenario_date: str = SCENARIO


def user_json(user):
    return {key: getattr(user,key) for key in ('id','email','role','organization_id','branch_ids','active')}
def plan_json(plan):
    return {**plan.result, **META, 'id':plan.id,'run_id':plan.id,'branch_id':plan.branch_id,'forecast_id':plan.forecast_id,'version':plan.version,'status':plan.status,'created_at':plan.created_at}
def forecast_json(forecast):
    return {**forecast.result, **META, 'id':forecast.id,'run_id':forecast.id,'branch_id':forecast.branch_id,'created_at':forecast.created_at}

def create_app(database_url=None):
    app = FastAPI(title='AsBoljam', version='1.0.0', description='Synthetic catering operations demo; one-day forecasts; internal approval only.')
    engine = make_engine(database_url)
    migrate(engine)
    atexit.register(engine.dispose)
    app.state.engine = engine
    app.state.sessions = sessions(engine)
    allowed_origins = [s.strip() for s in os.environ.get('ALLOWED_ORIGINS','http://localhost:3000,http://127.0.0.1:3000').split(',') if s.strip()]
    if '*' in allowed_origins:
        raise ValueError('ALLOWED_ORIGINS must contain exact origins; wildcard credentials are forbidden')
    secure = os.environ.get('COOKIE_SECURE','false').lower() == 'true'
    app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_credentials=True, allow_methods=['GET','POST','PATCH'], allow_headers=['Content-Type','X-CSRF-Token','Idempotency-Key','Authorization'])

    @app.middleware('http')
    async def protection(request, call_next):
        if request.method in {'POST','PATCH','PUT','DELETE'}:
            length = request.headers.get('content-length')
            if length and int(length) > 22 * 1024 * 1024:
                return JSONResponse({'detail':{'code':'FILE_TOO_LARGE','message':'Сұрау өлшемі шектен асты.'}},413)
        response = await call_next(request)
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['Referrer-Policy'] = 'same-origin'
        response.headers['Cache-Control'] = 'no-store'
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
        if not user or not user.active:
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
        if not user or not verify_password(data.password,user.password_hash) or not user.active:
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
        return {'status':'ok',**META}
    @app.post('/api/v1/session/login')
    def login(data: Login, request:Request,response:Response,db=Depends(get_db)):
        origin_check(request)
        user = authenticate(data,request,db)
        token,csrf = secrets.token_urlsafe(48),secrets.token_urlsafe(32)
        db.add(AuthSession(id=uid(),user_id=user.id,token_hash=token_hash(token),csrf_token=csrf,kind='web',expires_at=time.time()+8*3600))
        audit(db,user,'session.login',user.id)
        db.commit()
        response.set_cookie('asboljam_session',token,httponly=True,secure=secure,samesite='lax',max_age=8*3600,path='/api')
        return {'user':user_json(user),'csrf_token':csrf,**META}
    @app.get('/api/v1/session/me')
    def me(request:Request,user=Depends(current)):
        return {'user':user_json(user),'csrf_token':request.state.auth.csrf_token,**META}
    @app.post('/api/v1/session/logout')
    def logout(request:Request,response:Response,user=Depends(current),db=Depends(get_db)):
        request.state.auth.revoked=True
        if request.state.auth.family_id:
            db.execute(update(RefreshToken).where(RefreshToken.family_id==request.state.auth.family_id).values(revoked=True))
        db.commit()
        response.delete_cookie('asboljam_session',path='/api')
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
        if not old or old.revoked or old.expires_at<time.time():
            fail('REFRESH_INVALID','Қайта кіріңіз.',401)
        changed=db.execute(update(RefreshToken).where(RefreshToken.token_hash==old.token_hash,RefreshToken.used==False,RefreshToken.revoked==False).values(used=True)).rowcount
        if not changed:
            db.execute(update(RefreshToken).where(RefreshToken.family_id==old.family_id).values(revoked=True))
            db.execute(update(AuthSession).where(AuthSession.family_id==old.family_id).values(revoked=True))
            db.commit()
            fail('REFRESH_REUSED','Сессия қауіпсіздік үшін тоқтатылды.',401)
        user=db.get(User,old.user_id)
        if not user or not user.active:
            fail('AUTH_REQUIRED','Қайта кіріңіз.',401)
        db.execute(update(AuthSession).where(AuthSession.family_id==old.family_id).values(revoked=True))
        result=native_tokens(db,user,old.family_id)
        db.commit()
        return result

    def visible_rows(db,user,kind,branch=None):
        if branch:
            branch_access(db,user,branch)
        result=rows_for(db,user.organization_id,kind,branch if kind in {'daily_sales','calendar','inventory_lots'} else None)
        return [r for r in result if 'branch_id' not in r or r['branch_id'] in user.branch_ids and (not branch or r['branch_id']==branch)]
    def decorate(db,user,kind,rows):
        meals={r['meal_id']:r for r in rows_for(db,user.organization_id,'meals')}
        ingredients={r['ingredient_id']:r for r in rows_for(db,user.organization_id,'ingredients')}
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
                row['expired']=row['expiry_date']<SCENARIO
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
            return {'items':list(decorate(db,user,kind,rows[cursor:cursor+limit])),'total':len(rows),'next_cursor':str(cursor+limit) if cursor+limit<len(rows) else None,**META}
        endpoint.__name__='list_'+kind
        return endpoint
    for name,kind in aliases.items():
        app.add_api_route('/api/v1/'+name,list_endpoint(kind),methods=['GET'],response_model=CollectionResponse)

    @app.get('/api/v1/dashboard')
    def dashboard(branch_id:str,user=Depends(current),db=Depends(get_db)):
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
        lots=[r for r in rows_for(db,user.organization_id,'inventory_lots',branch_id) if r['snapshot_date']==SCENARIO]
        expiry_limit=(date.fromisoformat(SCENARIO)+timedelta(days=2)).isoformat()
        expired_count=sum(1 for r in lots if r['expiry_date']<SCENARIO)
        expiring_count=sum(1 for r in lots if SCENARIO<=r['expiry_date']<=expiry_limit)
        warnings=[]
        if expired_count:
            warnings.append({'code':'EXPIRED_LOTS','count':expired_count,'message':f'{expired_count} партияның жарамдылық мерзімі өткен.'})
        if expiring_count:
            warnings.append({'code':'EXPIRING_LOTS','count':expiring_count,'message':f'{expiring_count} партияның мерзімі екі күн ішінде аяқталады.'})
        last_plan=plans[0] if plans else None
        return {**META,'branch_id':branch_id,'as_of':last_date,'sold_portions':sum(r['units_sold'] for r in latest),'revenue':str(sum((Decimal(r['price_kzt'])*r['units_sold'] for r in latest),Decimal(0))),'total_shortages':last_plan.result.get('shortage_count',0) if last_plan else None,'procurement_cost':last_plan.result.get('total_cost') if last_plan else None,'history':[{'date':d,'units_sold':history[d]} for d in sorted(history)[-28:]],'top_meals':[{'meal_id':k,'meal_name':names.get(k,k),'units_sold':v['units_sold'],'revenue':str(v['revenue'])} for k,v in sorted(top.items(),key=lambda item:-item[1]['units_sold'])],'warnings':warnings,'latest_plans':[plan_json(p) for p in plans],'latest_forecast':forecast_json(forecasts[0]) if forecasts else None}

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
        roles(user,'admin','manager','analyst','warehouse')
        if user.role=='warehouse' and data.kind!='inventory_lots': roles(user,'admin','manager','analyst')
        if data.kind not in SCHEMAS: fail('UNSUPPORTED_KIND','Рұқсат етілмеген файл түрі.')
        if data.kind not in {'daily_sales','calendar','inventory_lots'}: roles(user,'admin')
        rows,errors=parse_csv(data.kind,data.csv_text)
        if not errors: errors=validate_rows(db,user.organization_id,data.kind,rows,user.branch_ids if data.kind!='branches' else None)
        batch=ImportBatch(id=uid(),organization_id=user.organization_id,actor_id=user.id,kind=data.kind,rows=rows,errors=errors)
        db.add(batch);db.commit()
        return {'id':batch.id,'kind':data.kind,'row_count':len(rows),'valid':not errors,'errors':errors,'preview':rows[:10],**META}
    @app.post('/api/v1/imports/{batch_id}/commit')
    def import_commit(batch_id:str,user=Depends(current),db=Depends(get_db)):
        batch=db.get(ImportBatch,batch_id)
        if not batch or batch.organization_id!=user.organization_id or batch.actor_id!=user.id: fail('NOT_FOUND','Импорт табылмады.',404)
        if user.role=='warehouse' and batch.kind!='inventory_lots': roles(user,'admin','manager','analyst')
        if batch.kind not in {'daily_sales','calendar','inventory_lots'}: roles(user,'admin')
        if batch.status!='preview': fail('ALREADY_COMMITTED','Импорт орындалған.',409)
        errors=batch.errors or validate_rows(db,user.organization_id,batch.kind,batch.rows,user.branch_ids if batch.kind!='branches' else None)
        if errors: fail('IMPORT_INVALID','Қателері бар импорт қабылданбайды.',422)
        try:
            changed=db.execute(update(ImportBatch).where(ImportBatch.id==batch_id,ImportBatch.status=='preview').values(status='committed')).rowcount
            if not changed: fail('ALREADY_COMMITTED','Импорт орындалған.',409)
            insert_rows(db,user.organization_id,batch.kind,batch.rows)
            if batch.kind=='branches':
                user.branch_ids=sorted(set(user.branch_ids) | {r['branch_id'] for r in batch.rows})
            for branch in {r.get('branch_id') for r in batch.rows}:
                audit(db,user,'import.committed',batch.id,branch,{'kind':batch.kind,'row_count':sum(1 for r in batch.rows if r.get('branch_id')==branch)})
            db.commit()
        except IntegrityError:
            db.rollback();fail('DUPLICATE_KEY','Қайталанған кілт: импорт толық тоқтатылды.',409)
        return {'id':batch.id,'status':'committed','row_count':len(batch.rows),**META}

    @app.post('/api/v1/forecasts',status_code=202,response_model=QueuedResponse)
    def create_forecast(data:ForecastInput,user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','analyst');branch_access(db,user,data.branch_id)
        sales=rows_for(db,user.organization_id,'daily_sales',data.branch_id)
        sales=[r for r in sales if r['date']<=data.origin.isoformat()]
        if not sales: fail('NO_SALES','Болжамға сатылым деректері қажет.',422)
        job=Job(id=uid(),organization_id=user.organization_id,branch_id=data.branch_id,actor_id=user.id,kind='forecast',payload=data.model_dump(mode='json'),snapshot={'sales':sales,'meals':rows_for(db,user.organization_id,'meals')})
        db.add(job);audit(db,user,'forecast.queued',job.id,data.branch_id);db.commit()
        return {'run_id':job.id,'status':'queued'}
    @app.get('/api/v1/runs/{run_id}')
    def run(run_id:str,user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','analyst')
        row=scoped(db,Job,user,run_id)
        return {k:getattr(row,k) for k in ('id','kind','status','result_id','error','created_at','finished_at')} | {'run_id':row.id,**META}
    @app.get('/api/v1/forecasts/{forecast_id}')
    def forecast_detail(forecast_id:str,user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','analyst')
        return forecast_json(scoped(db,Forecast,user,forecast_id))
    @app.get('/api/v1/forecasts')
    def forecast_list(branch_id:str|None=None,limit:int=Query(50,ge=1,le=200),cursor:int=Query(0,ge=0),user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','analyst')
        if branch_id: branch_access(db,user,branch_id)
        rows=list(db.scalars(select(Forecast).where(Forecast.organization_id==user.organization_id,Forecast.branch_id.in_([branch_id] if branch_id else user.branch_ids)).order_by(Forecast.created_at.desc())))
        return {'items':[forecast_json(r) for r in rows[cursor:cursor+limit]],'total':len(rows),'next_cursor':str(cursor+limit) if cursor+limit<len(rows) else None,**META}
    @app.post('/api/v1/procurement',status_code=202,response_model=QueuedResponse)
    def create_procurement(data:ProcurementInput,user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','analyst');branch_access(db,user,data.branch_id)
        forecast=scoped(db,Forecast,user,data.forecast_id)
        if forecast.branch_id!=data.branch_id: fail('BRANCH_MISMATCH','Болжам бөлімшесі сәйкес емес.',422)
        if data.strategy!='point' and any(r.get('p50' if data.strategy=='p50' else 'p90') is None for r in forecast.result['predictions']): fail('QUANTILES_UNAVAILABLE','Бұл модельде квантильдер жоқ.',422)
        snapshot={'forecast_result':forecast.result,**{k:rows_for(db,user.organization_id,k,data.branch_id if k=='inventory_lots' else None) for k in ['ingredients','recipes','inventory_lots','supplier_offers','suppliers']}}
        snapshot['inventory_lots']=[r for r in snapshot['inventory_lots'] if r['snapshot_date']==forecast.result['target_date']]
        if not snapshot['inventory_lots']: fail('STALE_INVENTORY','Қойма кесіндісі мақсат күніне сәйкес емес.',422)
        job=Job(id=uid(),organization_id=user.organization_id,branch_id=data.branch_id,actor_id=user.id,kind='procurement',payload=data.model_dump(mode='json'),snapshot=snapshot)
        db.add(job);audit(db,user,'procurement.queued',job.id,data.branch_id);db.commit()
        return {'run_id':job.id,'status':'queued'}
    @app.get('/api/v1/plans')
    def plan_list(branch_id:str|None=None,limit:int=Query(50,ge=1,le=200),cursor:int=Query(0,ge=0),user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','analyst')
        if branch_id: branch_access(db,user,branch_id)
        rows=list(db.scalars(select(Plan).where(Plan.organization_id==user.organization_id,Plan.branch_id.in_([branch_id] if branch_id else user.branch_ids)).order_by(Plan.created_at.desc())))
        return {'items':[plan_json(r) for r in rows[cursor:cursor+limit]],'total':len(rows),'next_cursor':str(cursor+limit) if cursor+limit<len(rows) else None,**META}
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
            if not plan.result.get('constraints_valid'): fail('CONSTRAINTS_INVALID','Шектеулері тексерілмеген жоспар бекітілмейді.',422)
            if plan.result.get('shortage_count',0)>0 and not data.acknowledge_shortage: fail('SHORTAGE_ACK_REQUIRED','Тапшылықты арнайы растау қажет.',422)
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
        return Response(safe_csv(rows),media_type='text/csv; charset=utf-8',headers={'Content-Disposition':f'attachment; filename="{actual}.csv"'})
    @app.get('/api/v1/plans/{plan_id}/export')
    def export_plan(plan_id:str,user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','analyst');plan=scoped(db,Plan,user,plan_id)
        common={'plan_id':plan.id,'status':plan.status,'version':plan.version,'target_date':plan.result.get('target_date'),'data_origin':'SYNTHETIC'}
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
        return {'items':[{k:getattr(r,k) for k in ('id','branch_id','actor_id','action','entity_id','details','created_at')} for r in rows[cursor:cursor+limit]],'total':len(rows),'next_cursor':str(cursor+limit) if cursor+limit<len(rows) else None,**META}
    @app.get('/api/v1/reports')
    def reports(branch_id:str,user=Depends(current),db=Depends(get_db)):
        roles(user,'admin','manager','analyst');branch_access(db,user,branch_id)
        rows=list(db.scalars(select(Forecast).where(Forecast.organization_id==user.organization_id,Forecast.branch_id==branch_id).order_by(Forecast.created_at.desc()).limit(20)))
        return {'items':[{'forecast_id':r.id,'created_at':r.created_at,'metrics':r.result.get('metrics',[]),'metadata':r.result.get('metadata',{})} for r in rows],**META}
    @app.get('/api/v1/settings')
    def settings(user=Depends(current)):
        return {**META,'organization':{'id':user.organization_id,'name':os.environ.get('ORGANIZATION_NAME','AsBoljam Demo')},'language':'kk-KZ','read_only':True,'user':user_json(user),'forecast_horizon_days':1}
    @app.get('/api/v1/users')
    def users(user=Depends(current),db=Depends(get_db)):
        roles(user,'admin')
        return {'items':[user_json(u) for u in db.scalars(select(User).where(User.organization_id==user.organization_id))],**META}
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
        other=db.get(User,user_id)
        if not other or other.organization_id!=user.organization_id: fail('NOT_FOUND','Пайдаланушы табылмады.',404)
        if other.id==user.id: fail('SELF_ACCESS_CHANGE','Өз рұқсатыңызды өзгертуге болмайды.',422)
        for branch in data.branch_ids: branch_access(db,user,branch)
        other.role,other.branch_ids,other.active=data.role,data.branch_ids,data.active
        db.execute(update(AuthSession).where(AuthSession.user_id==other.id).values(revoked=True))
        db.execute(update(RefreshToken).where(RefreshToken.user_id==other.id).values(revoked=True))
        audit(db,user,'user.access_changed',other.id,details=data.model_dump());db.commit()
        return user_json(other)
    return app

app=create_app()
