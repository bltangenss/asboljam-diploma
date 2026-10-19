import React, { useEffect, useRef, useState } from 'react';
import { ActivityIndicator, Alert, AppState, Platform, Pressable, ScrollView, StatusBar, StyleSheet, Switch, Text, TextInput, View } from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import * as SecureStore from 'expo-secure-store';
import { useNetworkState } from 'expo-network';
import { ApiError, type Page, type User } from '../../packages/api-client';
import { NativeSession } from './src/session';

type Tab = 'overview' | 'forecasts' | 'plans' | 'inventory' | 'more';
type Row = Record<string, any>;
const API = (process.env.EXPO_PUBLIC_API_URL || 'http://10.0.2.2:8000/api/v1').replace(/\/$/, '');
const STORAGE_KEY = 'asboljam.native.refresh.v1';
const session = new NativeSession(API, {
  read: () => SecureStore.getItemAsync(STORAGE_KEY),
  write: value => SecureStore.setItemAsync(STORAGE_KEY, value, { keychainAccessible: SecureStore.WHEN_UNLOCKED_THIS_DEVICE_ONLY }),
  clear: () => SecureStore.deleteItemAsync(STORAGE_KEY),
});

function AppContent() {
  const [language, setLanguage] = useState<'kk' | 'ru'>('kk');
  const t = (kk: string, ru: string) => language === 'kk' ? kk : ru;
  const [user, setUser] = useState<User | null>(null);
  const [booting, setBooting] = useState(true);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [tab, setTab] = useState<Tab>('overview');
  const [branches, setBranches] = useState<Row[]>([]);
  const [branch, setBranch] = useState('');
  const [detail, setDetail] = useState<{ kind: 'plans' | 'forecasts'; id: string } | null>(null);
  const [data, setData] = useState<Row | null>(null);
  const [items, setItems] = useState<Row[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [mealNames, setMealNames] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [apiUnavailable, setApiUnavailable] = useState(false);
  const [loadedAt, setLoadedAt] = useState('');
  const [reason, setReason] = useState('');
  const [acknowledge, setAcknowledge] = useState(false);
  const loadVersion = useRef(0);
  const decisionKey = useRef<{ fingerprint: string; key: string } | null>(null);
  const network = useNetworkState();
  // A local LAN API can be reachable without public internet access.
  const offline = network.isConnected === false || apiUnavailable;
  const money = (value: unknown) => value == null ? '—' : new Intl.NumberFormat(language === 'kk' ? 'kk-KZ' : 'ru-KZ', { style: 'currency', currency: 'KZT', maximumFractionDigits: 2 }).format(Number(value));
  const quantity = (value: unknown) => value == null ? '—' : Number(value).toLocaleString(language === 'kk' ? 'kk-KZ' : 'ru-KZ', { maximumFractionDigits: 2 });
  const status = (value: string) => ({ ready: t('Қарауға дайын', 'На согласовании'), approved: t('Бекітілді', 'Утверждён'), rejected: t('Қабылданбады', 'Отклонён') }[value] || value);

  function resetView() {
    ++loadVersion.current; setData(null); setItems([]); setCursor(null); setLoadedAt('');
    setDetail(null); setReason(''); setAcknowledge(false); decisionKey.current = null;
  }
  function report(error: unknown) {
    if (error instanceof ApiError) {
      if (error.status === 0) setApiUnavailable(true);
      if (error.status === 409) {
        setError(t('Жоспар нұсқасы өзгерді. Қайта жүктеп, қайта қараңыз.', 'Версия плана изменилась. Обновите и проверьте план.'));
        return;
      }
      if (error.status === 403) {
        setError(t('Бұл бөлімге рұқсат жоқ.', 'Нет доступа к этому разделу.')); return;
      }
    }
    setError(error instanceof Error ? error.message : t('Қате орын алды.', 'Произошла ошибка.'));
  }

  useEffect(() => {
    session.onUser = next => {
      setUser(next);
      if (next) setBranch(previous => next.branch_ids.includes(previous) ? previous : (next.branch_ids[0] || ""));
      if (!next) { resetView(); setBranches([]); setBranch(''); setMealNames({}); }
    };
    if (Platform.OS === 'web') {
      setError('Бұл native клиент. Веб-нұсқаны apps/web арқылы ашыңыз.'); setBooting(false); return;
    }
    session.restore().catch(report).finally(() => setBooting(false));
    return () => { session.onUser = () => {}; };
  }, []);

  useEffect(() => {
    if (!user) return;
    let active = true;
    (async () => {
      try {
        const response = await session.request<Page<Row>>('/branches?limit=200');
        if (!active) return;
        setBranches(response.items); setBranch(response.items[0]?.branch_id || '');
        setTab(user.role === 'warehouse' ? 'inventory' : 'overview');
        if (user.role !== 'warehouse') {
          const meals = await session.request<Page<Row>>('/meals?limit=200');
          if (active) setMealNames(Object.fromEntries(meals.items.map(meal => [meal.meal_id, meal.meal_name])));
        }
      } catch (error) { if (active) report(error); }
    })();
    return () => { active = false; };
  }, [user?.id]);

  async function load(append = false) {
    if (!user || !branch || tab === 'more' || network.isConnected === false) return;
    const version = ++loadVersion.current;
    setLoading(true); setError(''); setApiUnavailable(false);
    if (!append) { setData(null); setItems([]); setCursor(null); setLoadedAt(''); }
    const query = `branch_id=${encodeURIComponent(branch)}&limit=50${append && cursor ? `&cursor=${cursor}` : ''}`;
    const path = detail ? `/${detail.kind}/${encodeURIComponent(detail.id)}` : tab === 'overview' ? `/dashboard?branch_id=${encodeURIComponent(branch)}` : `/${tab}?${query}`;
    try {
      const result = await session.request<Row>(path);
      if (version !== loadVersion.current) return;
      if (detail && result.branch_id !== branch) throw new Error(t('Бөлімше сәйкес емес.', 'Филиал не совпадает.'));
      if (detail || tab === 'overview') setData(result);
      else { setItems(old => append ? [...old, ...result.items] : result.items); setCursor(result.next_cursor); }
      setLoadedAt(new Date().toLocaleTimeString(language === 'kk' ? 'kk-KZ' : 'ru-KZ'));
    } catch (error) { if (version === loadVersion.current) report(error); }
    finally { if (version === loadVersion.current) setLoading(false); }
  }
  useEffect(() => {
    setReason(''); setAcknowledge(false); decisionKey.current = null;
    void load();
    return () => { ++loadVersion.current; };
  }, [user?.id, branch, tab, detail?.id, network.isConnected]);
  useEffect(() => {
    const subscription = AppState.addEventListener('change', state => { if (state === 'active') void load(); });
    return () => subscription.remove();
  }, [user?.id, branch, tab, detail?.id, network.isConnected]);

  async function login() {
    if (busy || network.isConnected === false) return;
    setBusy(true); setError(''); setApiUnavailable(false);
    try { await session.login(email, password); setPassword(''); }
    catch (error) { report(error); }
    finally { setBusy(false); }
  }
  async function logout() {
    if (busy) return;
    setBusy(true); setError(''); setPassword('');
    try { await session.logout(); }
    catch {
      Alert.alert(t('Осы құрылғыдан шықтыңыз', 'Вы вышли на этом устройстве'), t('Жергілікті токен жойылды. Сервердегі сессияны қайтарып алу расталмады.', 'Локальный токен удалён. Отзыв сессии на сервере не подтверждён.'));
    } finally { setBusy(false); }
  }
  function open(kind: 'plans' | 'forecasts', id: string) { resetView(); setTab(kind); setDetail({ kind, id }); }
  async function decide(action: 'approve' | 'reject') {
    if (offline || busy || !data || !detail || data.status !== 'ready' || !['admin', 'manager'].includes(user?.role || '')) return;
    if (reason.trim().length < 3 || (action === 'approve' && data.shortage_count > 0 && !acknowledge)) return;
    const payload = { expected_version: data.version, reason: reason.trim(), acknowledge_shortage: acknowledge };
    const fingerprint = JSON.stringify({ id: data.id, action, ...payload });
    if (decisionKey.current?.fingerprint !== fingerprint) decisionKey.current = { fingerprint, key: `mobile-${Date.now()}-${Math.random().toString(36).slice(2)}` };
    const key = decisionKey.current.key;
    setBusy(true); setError('');
    try {
      const result = await session.request<Row>(`/plans/${encodeURIComponent(data.id)}/${action}`, { method: 'POST', body: JSON.stringify(payload), headers: { 'Idempotency-Key': key } });
      setData(result); setReason(''); setAcknowledge(false);
    } catch (error) { report(error); }
    finally { setBusy(false); }
  }
  function confirm(action: 'approve' | 'reject') {
    Alert.alert(t('Шешімді растаңыз', 'Подтвердите решение'), t('Бұл әрекет жеткізушіге тапсырыс жібермейді.', 'Это действие не отправляет заказ поставщику.'), [
      { text: t('Бас тарту', 'Отмена'), style: 'cancel' },
      { text: action === 'approve' ? t('Бекіту', 'Утвердить') : t('Қабылдамау', 'Отклонить'), onPress: () => { void decide(action); } },
    ]);
  }
  const button = (label: string, onPress: () => void, disabled = false, secondary = false) => <Pressable accessibilityRole="button" accessibilityState={{ disabled }} disabled={disabled} onPress={onPress} style={[styles.button, secondary && styles.secondary, disabled && styles.disabled]}><Text style={[styles.buttonText, secondary && styles.secondaryText]}>{label}</Text></Pressable>;
  const card = (title: string, children: React.ReactNode, key?: string) => <View key={key} style={styles.card}><Text style={styles.cardTitle}>{title}</Text>{children}</View>;
  const line = (label: string, value: React.ReactNode) => <View style={styles.line}><Text style={styles.label}>{label}</Text><Text style={styles.value}>{value}</Text></View>;
  const planCard = (plan: Row) => <Pressable accessibilityRole="button" accessibilityLabel={t('Жоспарды ашу', 'Открыть план')} key={plan.id} onPress={() => open('plans', plan.id)} style={styles.card}><Text style={styles.cardTitle}>{t('Сатып алу жоспары', 'План закупки')} →</Text><Text style={styles.big}>{money(plan.total_cost)}</Text>{line(plan.target_date, status(plan.status))}{line(t('Тапшылықты ингредиенттер', 'Ингредиенты с дефицитом'), String(plan.shortage_count))}</Pressable>;
  const tabs: { id: Tab; kk: string; ru: string; mark: string }[] = [
    { id: 'overview', kk: 'Шолу', ru: 'Обзор', mark: '◫' }, { id: 'forecasts', kk: 'Болжам', ru: 'Прогноз', mark: '↗' },
    { id: 'plans', kk: 'Сатып алу', ru: 'Закупки', mark: '▤' }, { id: 'inventory', kk: 'Қойма', ru: 'Склад', mark: '▧' }, { id: 'more', kk: 'Тағы', ru: 'Ещё', mark: '•••' },
  ];

  if (booting) return <SafeAreaView style={styles.center}><ActivityIndicator color="#166b53"/><Text style={styles.subtitle}>{t('Сессия тексерілуде…', 'Проверка сессии…')}</Text></SafeAreaView>;
  return <SafeAreaView style={styles.shell} edges={['top', 'bottom']}>
    <StatusBar barStyle="dark-content" backgroundColor="#f4f6f2"/>
    <View style={styles.header}><View style={styles.logo}><Text style={styles.logoText}>p</Text></View><View style={{ flex: 1 }}><Text style={styles.brand}>predas</Text><Text style={styles.subtitle}>{t('Ертеңгі сұранысты бүгін біліңіз', 'Знайте завтрашний спрос сегодня')}</Text></View><Pressable accessibilityRole="button" onPress={() => setLanguage(language === 'kk' ? 'ru' : 'kk')} style={styles.language}><Text>{language === 'kk' ? 'RU' : 'ҚАЗ'}</Text></Pressable></View>
    <View style={styles.demo}><Text style={styles.demoText}>{t('Демо: жасанды деректер', 'Демо: синтетические данные')} · 01.01.2026</Text></View>
    {offline && <View style={styles.warning}><Text style={styles.warningText}>{t('Сервермен байланыс жоқ. Әрекеттер жіберілмейді.', 'Нет связи с сервером. Действия не отправляются.')}</Text></View>}
    <ScrollView contentContainerStyle={styles.content} keyboardShouldPersistTaps="handled">
      {!!error && <View accessibilityRole="alert" style={styles.error}><Text style={styles.errorText}>{error}</Text></View>}
      {!user ? <>
        <Text style={styles.eyebrow}>{t('КОМАНДАҢЫЗДЫҢ ЖҰМЫС ОРНЫ', 'РАБОЧЕЕ МЕСТО КОМАНДЫ')}</Text>
        <Text style={styles.title}>{t('Қош келдіңіз.', 'Добро пожаловать.')}</Text>
        <Text style={styles.intro}>{t('Сатылым, болжам және сатып алу — бір жүйеде.', 'Продажи, прогнозы и закупки в одной системе.')}</Text>
        {card(t('Жүйеге кіру', 'Вход в систему'), <>
          <Text style={styles.label}>{t('Электрондық пошта', 'Электронная почта')}</Text><TextInput accessibilityLabel={t('Электрондық пошта', 'Электронная почта')} value={email} onChangeText={setEmail} autoCapitalize="none" autoCorrect={false} keyboardType="email-address" textContentType="username" style={styles.input}/>
          <Text style={styles.label}>{t('Құпиясөз', 'Пароль')}</Text><TextInput accessibilityLabel={t('Құпиясөз', 'Пароль')} value={password} onChangeText={setPassword} secureTextEntry textContentType="password" style={styles.input}/>
          {button(busy ? t('Кіру…', 'Вход…') : t('Кіру →', 'Войти →'), () => { void login(); }, busy || !email || !password || network.isConnected === false || Platform.OS === 'web')}
        </>)}
        {apiUnavailable && button(t('Сессияны қайта тексеру', 'Проверить сохранённую сессию'), () => { setApiUnavailable(false); setError(''); session.restore().catch(report); }, busy, true)}
      </> : <>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.branches}>{(branches.length ? branches : user.branch_ids.map(id => ({ branch_id: id, branch_name: `${t("Бөлімше", "Филиал")} ${id}` }))).map(item => <Pressable key={item.branch_id} accessibilityRole="button" accessibilityState={{ selected: item.branch_id === branch }} disabled={busy} style={[styles.chip, item.branch_id === branch && styles.chipActive]} onPress={() => { if (item.branch_id !== branch) { resetView(); setBranch(item.branch_id); } }}><Text style={item.branch_id === branch ? styles.chipActiveText : styles.chipText}>{item.branch_name}</Text></Pressable>)}</ScrollView>
        <View style={styles.titleRow}><Text style={styles.pageTitle}>{t(tabs.find(item => item.id === tab)!.kk, tabs.find(item => item.id === tab)!.ru)}</Text>{tab !== 'more' && button(t('Жаңарту', 'Обновить'), () => { void load(); }, loading || busy || network.isConnected === false, true)}</View>
        {!!loadedAt && <Text style={styles.meta}>{t('Серверден алынды', 'Получено с сервера')}: {loadedAt}{offline ? t(' · ескірген деректер', ' · данные могут устареть') : ''}</Text>}
        {detail && button(t('← Тізімге', '← К списку'), () => { resetView(); }, busy, true)}
        {loading && <ActivityIndicator color="#166b53" style={{ margin: 20 }}/>}
        {!loading && !data && !items.length && tab !== 'more' && !error && <Text style={styles.empty}>{t('Әзірге деректер жоқ. Веб-жүйеде есеп құрып, жаңартыңыз.', 'Пока нет данных. Создайте расчёт в веб-системе и обновите.')}</Text>}
        {tab === 'overview' && data && <>
          {card(t('Соңғы сатылым күні', 'Последний день продаж'), <><Text style={styles.big}>{quantity(data.sold_portions)} <Text style={styles.unit}>{t('порция', 'порций')}</Text></Text>{line(t('Күні', 'Дата'), data.as_of)}{line(t('Шартты түсім', 'Условная выручка'), money(data.revenue))}</>)}
          {card(t('Сатып алу шолуы', 'Обзор закупок'), <>{line(t('Соңғы жоспар құны', 'Стоимость последнего плана'), money(data.procurement_cost))}{line(t('Тапшылықты ингредиенттер', 'Ингредиенты с дефицитом'), data.total_shortages ?? '—')}</>)}
          {(data.latest_plans || []).map(planCard)}
          {card(t('Сұраныстағы тағамдар', 'Популярные блюда'), (data.top_meals || []).slice(0, 5).map((meal: Row) => <View key={meal.meal_id}>{line(meal.meal_name, `${quantity(meal.units_sold)} ${t('порция', 'порций')}`)}</View>))}
        </>}
        {tab === 'plans' && !detail && items.map(planCard)}
        {tab === 'forecasts' && !detail && items.map(forecast => <Pressable accessibilityRole="button" key={forecast.id} onPress={() => open('forecasts', forecast.id)} style={styles.card}><Text style={styles.cardTitle}>{forecast.target_date} →</Text>{line(t('Модель', 'Модель'), forecast.model)}{line(t('Тағамдар', 'Блюд'), forecast.predictions?.length || 0)}</Pressable>)}
        {detail?.kind === 'forecasts' && data && <>
          {card(t('Болжам туралы', 'О прогнозе'), <>{line(t('Модель', 'Модель'), data.model)}{line(t('Тарих шекарасы', 'Граница истории'), data.origin)}{line(t('Мақсат күні', 'Целевая дата'), data.target_date)}<Text style={styles.note}>{t('Бір күндік сатылым болжамы. p10–p90: номинал 80% аралық.', 'Однодневный прогноз продаж. p10–p90: номинальный интервал 80%.')}</Text></>)}
          {(data.predictions || []).map((prediction: Row) => card(mealNames[prediction.meal_id] || `${t('Тағам', 'Блюдо')} ${prediction.meal_id}`, <><Text style={styles.big}>{quantity(prediction.point_forecast)}</Text><Text style={styles.note}>{prediction.p10 == null ? t('Квантильдер есептелмеген', 'Квантили не рассчитаны') : `p10 ${quantity(prediction.p10)} · p50 ${quantity(prediction.p50)} · p90 ${quantity(prediction.p90)}`}</Text></>, prediction.meal_id))}
        </>}
        {detail?.kind === 'plans' && data && <>
          {card(t('Жоспар туралы', 'О плане'), <><Text style={styles.big}>{money(data.total_cost)}</Text>{line(t('Күйі', 'Статус'), status(data.status))}{line(t('Нұсқа', 'Версия'), data.version)}{line(t('Күні', 'Дата'), data.target_date)}{line(t('Бюджет', 'Бюджет'), money(data.budget))}{line(t('Қалған бюджет', 'Остаток бюджета'), money(data.remaining_budget))}{line(t('Стратегия', 'Стратегия'), data.strategy)}{line(t('Тапшылықты ингредиенттер', 'Ингредиенты с дефицитом'), data.shortage_count)}{line(t('Шешуші', 'Решатель'), data.solver_status)}{line(t('Шектеулер тексерілді', 'Ограничения проверены'), data.constraints_valid ? '✓' : '—')}<Text selectable style={styles.meta}>ID: {data.id}</Text><Text style={styles.note}>{t('Қор кесіндісі', 'Снимок склада')}: {data.metadata?.snapshot_date || '—'}</Text>{data.strategy === 'p90_stress' && <Text style={styles.warningText}>{t('p90 жиынтығы — сценарий, 90% қамтамасыз ету кепілдігі емес.', 'Сумма p90 — сценарий без гарантии обеспеченности 90%.')}</Text>}</>)}
          {(data.requirements || []).map((item: Row) => card(item.ingredient_name || item.name || item.ingredient_id, <>{line(t('Қажеттілік', 'Потребность'), `${quantity(item.gross_required)} ${item.unit}`)}{line(t('Жарамды қалдық', 'Пригодный запас'), `${quantity(item.usable_stock)} ${item.unit}`)}{line(t('Сатып алу', 'Закупка'), `${quantity(item.purchased_qty)} ${item.unit}`)}{line(t('Тапшылық', 'Дефицит'), `${quantity(item.shortage_qty)} ${item.unit}`)}{line(t('Артық қор', 'Излишек'), `${quantity(item.excess_qty)} ${item.unit}`)}</>, item.ingredient_id))}
          {card(t('Тапсырыс жолдары', 'Строки плана'), (data.lines || []).map((item: Row, index: number) => <View key={index} style={styles.order}><Text style={styles.cardTitle}>{item.supplier_name}</Text><Text style={styles.note}>{item.ingredient_id} · {item.packs} × {quantity(item.pack_qty)} {item.unit}</Text><Text style={styles.value}>{money(item.line_cost_kzt)}</Text></View>))}
          {data.status === 'ready' && ['manager', 'admin'].includes(user.role) && card(t('Менеджер шешімі', 'Решение менеджера'), <>
            <Text style={styles.note}>{t('Бұл әрекет жеткізушіге тапсырыс жібермейді.', 'Это действие не отправляет заказ поставщику.')}</Text>
            <TextInput accessibilityLabel={t('Шешім себебі', 'Причина решения')} placeholder={t('Себеп (кемінде 3 таңба)', 'Причина (минимум 3 символа)')} value={reason} onChangeText={setReason} editable={!busy} maxLength={1000} multiline style={[styles.input, { minHeight: 80 }]}/>
            {data.shortage_count > 0 && <View style={styles.line}><Text style={[styles.label, { flex: 1 }]}>{t('Тапшылықты көрдім және растаймын', 'Я ознакомился с дефицитом')}</Text><Switch accessibilityLabel={t('Тапшылықты растау', 'Подтверждение дефицита')} value={acknowledge} onValueChange={setAcknowledge} disabled={busy || offline}/></View>}
            {button(t('Жоспарды бекіту', 'Утвердить план'), () => confirm('approve'), busy || offline || reason.trim().length < 3 || !data.constraints_valid || (data.shortage_count > 0 && !acknowledge))}
            {button(t('Қабылдамау', 'Отклонить'), () => confirm('reject'), busy || offline || reason.trim().length < 3, true)}
          </>)}
        </>}
        {tab === 'inventory' && items.map((item, index) => card(item.ingredient_name || item.ingredient_id, <>{line(t('Партия', 'Партия'), item.lot_id)}{line(t('Қалдық', 'Остаток'), `${quantity(item.on_hand_qty)} ${item.unit}`)}{line(t('Қор кесіндісі', 'Дата снимка'), item.snapshot_date)}{line(t('Жарамды күні', 'Годен до'), item.expiry_date)}{item.expired && <Text style={styles.warningText}>{t('Сценарий күніне жарамсыз', 'Просрочено на дату сценария')}</Text>}</>, `${item.lot_id}-${index}`))}
        {cursor && !detail && button(t('Тағы жүктеу', 'Загрузить ещё'), () => { void load(true); }, loading || offline, true)}
        {tab === 'more' && <>
          {card(t('Профиль', 'Профиль'), <>{line(t('Пошта', 'Почта'), user.email)}{line(t('Рөл', 'Роль'), user.role)}{line(t('Ұйым', 'Организация'), user.organization_id)}</>)}
          {card(t('Қосымша туралы', 'О приложении'), <Text style={styles.note}>{t('SYNTHETIC · Бір күндік сценарий. Есептеу серверде орындалады. Бұл құрылғыда деректер кэші және офлайн әрекет кезегі жоқ.', 'SYNTHETIC · Однодневный сценарий. Расчёты выполняются на сервере. На устройстве нет кеша данных и очереди офлайн-действий.')}</Text>)}
          {button(t('Жүйеден шығу', 'Выйти'), () => { void logout(); }, busy, true)}
        </>}
      </>}
    </ScrollView>
    {user && <View style={styles.tabs}>{tabs.map(item => <Pressable accessibilityRole="tab" accessibilityState={{ selected: item.id === tab }} key={item.id} onPress={() => { if (!busy && (item.id !== tab || detail)) { resetView(); setTab(item.id); } }} style={[styles.tab, item.id === tab && styles.tabActive]}><Text style={[styles.tabMark, item.id === tab && styles.tabTextActive]}>{item.mark}</Text><Text style={[styles.tabText, item.id === tab && styles.tabTextActive]}>{t(item.kk, item.ru)}</Text></Pressable>)}</View>}
  </SafeAreaView>;
}
export default function App() { return <SafeAreaProvider><AppContent/></SafeAreaProvider>; }

const styles = StyleSheet.create({
  shell: { flex: 1, backgroundColor: '#f4f6f2' }, center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 16 },
  header: { flexDirection: 'row', alignItems: 'center', padding: 20, gap: 12 }, logo: { backgroundColor: '#FF5A1F', width: 42, height: 42, borderRadius: 12, alignItems: 'center', justifyContent: 'center' }, logoText: { fontSize: 27, color: '#fff', fontWeight: '800' }, brand: { fontSize: 24, fontWeight: '800', color: '#173c31' }, subtitle: { fontSize: 11, color: '#65746c', marginTop: 3 }, language: { padding: 12, borderWidth: 1, borderColor: '#dbe4dc', borderRadius: 12 },
  demo: { paddingHorizontal: 20, paddingVertical: 10, backgroundColor: '#e2efe2' }, demoText: { color: '#2c573b', fontSize: 11, fontWeight: '600' }, content: { padding: 20, paddingBottom: 32, gap: 14 }, eyebrow: { fontSize: 10, letterSpacing: 1.5, color: '#66756c', marginTop: 28 }, title: { fontSize: 36, fontWeight: '700', color: '#173c31' }, intro: { fontSize: 16, lineHeight: 25, color: '#65746c', marginBottom: 10 },
  titleRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 8 }, pageTitle: { fontSize: 26, fontWeight: '700', color: '#173c31' }, card: { backgroundColor: '#fff', borderRadius: 18, padding: 18, borderWidth: 1, borderColor: '#e3e8e2', gap: 10 }, cardTitle: { fontSize: 15, fontWeight: '700', color: '#253d32' }, big: { fontSize: 30, fontWeight: '700', color: '#173c31', marginVertical: 4 }, unit: { fontSize: 14, fontWeight: '400', color: '#65746c' }, line: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 14, paddingVertical: 5 }, label: { color: '#68756c', fontSize: 12, flexShrink: 1 }, value: { color: '#253d32', fontSize: 13, fontWeight: '600', flexShrink: 1, textAlign: 'right' }, input: { borderWidth: 1, borderColor: '#cfdbd0', backgroundColor: '#fafbf9', borderRadius: 10, minHeight: 46, padding: 12, color: '#253d32', fontSize: 15 },
  button: { backgroundColor: '#166b53', borderRadius: 10, paddingHorizontal: 16, paddingVertical: 13, alignItems: 'center', minHeight: 44 }, buttonText: { color: '#fff', fontSize: 13, fontWeight: '700' }, secondary: { backgroundColor: '#e9eee8' }, secondaryText: { color: '#28543f' }, disabled: { opacity: 0.45 }, note: { color: '#65746c', fontSize: 12, lineHeight: 19 }, meta: { fontSize: 10, color: '#65746c' }, empty: { color: '#65746c', lineHeight: 22, textAlign: 'center', paddingVertical: 30 }, error: { padding: 14, borderRadius: 10, backgroundColor: '#fbe8e5' }, errorText: { color: '#8d2e24', lineHeight: 20 }, warning: { backgroundColor: '#fff1d4', padding: 12 }, warningText: { color: '#785016', fontSize: 12, lineHeight: 20 },
  branches: { flexDirection: 'row', gap: 8, paddingBottom: 4 }, chip: { borderWidth: 1, borderColor: '#d5e0d7', borderRadius: 20, paddingHorizontal: 15, paddingVertical: 10 }, chipActive: { backgroundColor: '#173c31', borderColor: '#173c31' }, chipText: { color: '#53655a', fontSize: 12 }, chipActiveText: { color: '#fff', fontSize: 12, fontWeight: '600' }, order: { borderBottomWidth: 1, borderBottomColor: '#edf0eb', paddingVertical: 9, gap: 7 },
  tabs: { flexDirection: 'row', backgroundColor: '#fff', borderTopWidth: 1, borderTopColor: '#e0e7df', paddingVertical: 8, paddingHorizontal: 4 }, tab: { flex: 1, alignItems: 'center', paddingVertical: 8, gap: 4, borderRadius: 12 }, tabActive: { backgroundColor: '#eaf3e7' }, tabMark: { fontSize: 22, color: '#728176' }, tabText: { fontSize: 9, color: '#728176' }, tabTextActive: { color: '#166b53', fontWeight: '700' },
});
