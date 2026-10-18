import {useEffect,useRef,useState,type ReactNode} from 'react';
import {X} from 'lucide-react';
import type {Lang} from './shared';

// Secondary material (history, past runs, evidence) opens as a sheet over the page instead
// of occupying a column or a stack of disclosures under it. The <details> element keeps the
// open state, so keyboard, tests and links behave as before. Markup contract: the backdrop
// is rendered right before the `.sheet` element inside the same <details>.
const open:HTMLElement[]=[];
const focusable='a[href],button:not([disabled]),input:not([disabled]),select:not([disabled]),textarea:not([disabled]),summary,[tabindex]:not([tabindex="-1"])';

export function SheetBackdrop({close}:{close:()=>void}){
 const ref=useRef<HTMLDivElement>(null),closeRef=useRef(close);closeRef.current=close;
 useEffect(()=>{
  const backdrop=ref.current,sheet=backdrop?.nextElementSibling as HTMLElement|null;
  const summary=backdrop?.parentElement?.querySelector<HTMLElement>(':scope>summary')??null;
  if(!sheet)return;
  open.push(sheet);document.body.classList.add('sheet-open');
  sheet.setAttribute('role','dialog');sheet.setAttribute('aria-modal','true');sheet.tabIndex=-1;
  if(summary?.textContent)sheet.setAttribute('aria-label',summary.textContent.trim());
  sheet.focus({preventScroll:true});
  // Only the most recently opened sheet answers keys; the command palette handles its own Esc.
  const key=(event:KeyboardEvent)=>{
   if(open[open.length-1]!==sheet||event.defaultPrevented)return;
   if(event.key==='Escape'){event.preventDefault();closeRef.current();return}
   if(event.key!=='Tab')return;
   const items=[...sheet.querySelectorAll<HTMLElement>(focusable)].filter(item=>item.offsetParent!==null);
   if(!items.length){event.preventDefault();sheet.focus();return}
   const first=items[0],last=items[items.length-1],active=document.activeElement;
   if(event.shiftKey&&(active===first||active===sheet||!sheet.contains(active))){event.preventDefault();last.focus()}
   else if(!event.shiftKey&&(active===last||!sheet.contains(active))){event.preventDefault();first.focus()}
  };
  document.addEventListener('keydown',key);
  return()=>{
   document.removeEventListener('keydown',key);
   const index=open.indexOf(sheet);if(index>=0)open.splice(index,1);
   if(!open.length)document.body.classList.remove('sheet-open');
   ['role','aria-modal','aria-label','tabindex'].forEach(name=>sheet.removeAttribute(name));
   const active=document.activeElement;
   if(summary?.isConnected&&(!active||active===document.body||sheet.contains(active)))summary.focus({preventScroll:true});
  };
 },[]);
 return <div ref={ref} className="sheet-backdrop" aria-hidden="true" onClick={()=>closeRef.current()}/>;
}
export function SheetClose({close,lang}:{close:()=>void;lang:Lang}){
 return <button type="button" className="icon-button sheet-close" aria-label={lang==='kk'?'Жабу':'Закрыть'} onClick={close}><X size={18}/></button>;
}
// A toolbar chip whose content opens as a sheet. Chips sharing a `group` behave like tabs:
// opening one closes the other (native exclusive <details name>). Callers key it by record id.
export function SheetDetails({className,summary,lang,group,children}:{className?:string;summary:ReactNode;lang:Lang;group?:string;children:ReactNode}){
 const[isOpen,setOpen]=useState(false),close=()=>setOpen(false);
 return <details className={className} name={group} open={isOpen} onToggle={event=>setOpen(event.currentTarget.open)}><summary>{summary}</summary>{isOpen&&<SheetBackdrop close={close}/>}<div className="sheet"><SheetClose close={close} lang={lang}/>{children}</div></details>;
}
