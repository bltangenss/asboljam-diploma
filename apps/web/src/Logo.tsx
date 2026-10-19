// Predas = pred(ict) + ас (food in Kazakh). The mark is a lowercase p whose bowl is a dish
// under its rim: the name's first letter and a meal in one stroke, legible at 16 px.
// Technical identifiers (cookies, environment names, demo e-mails) keep the old name.
export const BRAND='Predas';

export function LogoMark({size=28}:{size?:number}){
 return <svg className="logo-mark" width={size} height={size} viewBox="0 0 32 32" aria-hidden="true" focusable="false">
  <rect width="32" height="32" rx="8" fill="#FF5A1F"/>
  <g fill="none" stroke="#fff" strokeWidth="4.2" strokeLinecap="round" strokeLinejoin="round">
   <path d="M10 8V25"/><path d="M10 8H25.5"/><path d="M24 8A7 7 0 0 1 17 15A7 7 0 0 1 10 8"/>
  </g>
 </svg>;
}

export function Logo({size=28}:{size?:number}){
 return <span className="logo"><LogoMark size={size}/><span className="logo-word">predas</span></span>;
}
