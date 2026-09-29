import {useEffect, useRef, useState, type FormEvent} from 'react';
import {ShieldCheck} from 'lucide-react';
import {ApiError} from '../../../packages/api-client';
import {api, Button, type Context} from './shared';

export default function AccountSecurity({t, online, user}:Context) {
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirmation, setConfirmation] = useState('');
  const [errorKey, setErrorKey] = useState('');
  const [busy, setBusy] = useState(false);
  const pending = useRef(false);
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {mounted.current = false};
  }, []);

  function clearPasswords() {
    setCurrentPassword(''); setNewPassword(''); setConfirmation('');
  }

  async function submit(event:FormEvent) {
    event.preventDefault();
    if (pending.current || !online) return;
    setErrorKey('');
    if (!currentPassword) {setErrorKey('currentPasswordRequired'); return}
    const length = Array.from(newPassword).length;
    if (length < 12 || length > 1024) {setErrorKey('passwordLength'); return}
    if (newPassword !== confirmation) {setErrorKey('passwordMismatch'); return}
    const session = api.csrf;
    if (!session) return;
    pending.current = true;
    setBusy(true);
    try {
      const result = await api.post<{status:string;reauth_required:boolean}>('/account/password', {
        current_password:currentPassword, new_password:newPassword,
      });
      if (result.status !== 'password_changed' || result.reauth_required !== true) {
        throw new Error('Unconfirmed password change');
      }
      // The server revoked this session. A late response must not reset a newer login.
      // Navigation away does not keep a revoked session alive in the app.
      if (api.csrf === session) {
        if (mounted.current) clearPasswords();
        api.csrf = '';
        api.onUnauthorized?.(new ApiError(401, 'PASSWORD_CHANGED', 'Password changed'));
      }
    } catch (error) {
      if (mounted.current && api.csrf === session) {
        clearPasswords();
        const code = error instanceof ApiError ? error.code : '';
        setErrorKey(code === 'CURRENT_PASSWORD_INVALID' ? 'currentPasswordInvalid'
          : code === 'PASSWORD_UNCHANGED' ? 'passwordUnchanged' : 'passwordChangeFailed');
      }
    } finally {
      pending.current = false;
      if (mounted.current) setBusy(false);
    }
  }

  return <section aria-labelledby="account-security-heading" className="user-admin">
    <div className="panel-heading"><div>
      <h2 id="account-security-heading">{t('accountSecurity')}</h2>
      <p>{t('passwordChangeHint')}</p>
    </div><ShieldCheck size={22}/></div>
    <form className="admin-form" aria-label={t('changePassword')} onSubmit={submit} noValidate>
      {/* Associates password-manager suggestions with this account without persisting secrets. */}
      <input type="text" name="username" value={user.email} autoComplete="username" readOnly hidden/>
      {errorKey && <div className="alert danger" role="alert">{t(errorKey)}</div>}
      <div className="filters">
        <label htmlFor="current-password">{t('currentPassword')}
          <input id="current-password" name="current_password" type="password" autoComplete="current-password"
            required maxLength={1024} disabled={busy} value={currentPassword}
            onChange={event=>setCurrentPassword(event.target.value)}/>
        </label>
        <label htmlFor="new-password"><span id="new-password-label">{t('newPassword')}</span>
          <input id="new-password" name="new_password" type="password" autoComplete="new-password"
            required minLength={12} maxLength={1024} disabled={busy} value={newPassword}
            aria-labelledby="new-password-label" aria-describedby="password-length-hint" onChange={event=>setNewPassword(event.target.value)}/>
          <small id="password-length-hint">{t('passwordLength')}</small>
        </label>
        <label htmlFor="confirm-password">{t('confirmPassword')}
          <input id="confirm-password" name="confirm_password" type="password" autoComplete="new-password"
            required minLength={12} maxLength={1024} disabled={busy} value={confirmation}
            onChange={event=>setConfirmation(event.target.value)}/>
        </label>
      </div>
      <div className="panel-actions">
        {busy && <span role="status">{t('passwordChanging')}</span>}
        <Button type="submit" disabled={busy || !online}>{t('changePassword')}</Button>
      </div>
    </form>
  </section>;
}
