import {useId, useLayoutEffect, useRef, useState, type AnchorHTMLAttributes, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes} from 'react';

export type NavigationItem = {id: string; label: string; href: string; current?: boolean};
export type SiteAction = {label: string; href: string; external?: boolean} | {label: string; onClick: () => void; disabled?: boolean};
export type Brand = {label: string; href: string; imageSrc?: string};
export type SiteShellProps = {
  brand: Brand; navigation?: readonly NavigationItem[]; account?: Brand;
  primaryAction?: SiteAction; footer?: ReactNode; children: ReactNode;
  mainId?: string; className?: string;
};

function Action({action, className = ''}: {action: SiteAction; className?: string}) {
  return 'href' in action ? <a className={className} href={action.href} target={action.external ? '_blank' : undefined} rel={action.external ? 'noopener noreferrer' : undefined}>{action.label}</a>
    : <button type="button" className={className} disabled={action.disabled} onClick={action.onClick}>{action.label}</button>;
}

export function SiteShell({brand, navigation = [], account, primaryAction, footer, children, mainId = 'main', className = ''}: SiteShellProps) {
  const header = useRef<HTMLElement>(null);
  // The header's actual wrapped height also offsets Workspace navigation.
  useLayoutEffect(() => {
    const element = header.current;
    if (!element) return;
    const update = () => element.closest<HTMLElement>('.tashan-shell')?.style.setProperty('--sample-header-height', `${element.getBoundingClientRect().height}px`);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const links = () => navigation.map(item => <a key={item.id} href={item.href} aria-current={item.current ? 'page' : undefined}>{item.label}</a>);
  return <div className={`sample-site tashan-shell ${className}`}>
    <a className="skip-link" href={`#${mainId}`} onClick={event => {event.preventDefault(); document.getElementById(mainId)?.focus();}}>跳转正文</a>
    <header className="site-header" ref={header}><div className="frame header-inner">
      <a className="brand" href={brand.href}>{brand.imageSrc ? <img src={brand.imageSrc} alt={brand.label} width="240" height="38"/> : <span>{brand.label}</span>}</a>
      <nav className="desktop-nav" aria-label="主导航">{links()}</nav>
      <div className="header-actions">
        {account ? <a className="account-entry" href={account.href} aria-label={account.label}>{account.imageSrc ? <img className="account-avatar-image" src={account.imageSrc} alt=""/> : <svg className="icon" aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"><circle cx="12" cy="7" r="4"/><path d="M4 22v-3a8 8 0 0 1 16 0v3"/></svg>}<span data-account-label="">{account.label}</span></a> : null}
        {primaryAction ? <Action action={primaryAction} className="join-button"/> : null}
      </div>
    </div>{navigation.length ? <nav className="sample-mobile-menu frame" aria-label="手机主导航">{links()}</nav> : null}</header>
    <main id={mainId} tabIndex={-1}>{children}</main>
    {footer ? <footer className="site-footer"><div className="frame footer-inner">{footer}</div></footer> : null}
  </div>;
}

export type PageHeadingProps = {title: string; description?: ReactNode; eyebrow?: string; actions?: ReactNode};
export function PageHeading({title, description, eyebrow, actions}: PageHeadingProps) {
  return <header className="tw-page-heading"><div>{eyebrow ? <p className="tw-eyebrow">{eyebrow}</p> : null}<h1>{title}</h1>{description ? <div className="tw-page-description">{description}</div> : null}</div>{actions ? <div className="tw-actions">{actions}</div> : null}</header>;
}

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {variant?: 'primary' | 'secondary' | 'quiet'};
export function Button({variant = 'primary', type = 'button', className = '', ...props}: ButtonProps) {
  return <button {...props} type={type} className={`button tw-button ${variant === 'secondary' ? 'secondary' : variant === 'quiet' ? 'tw-quiet' : ''} ${className}`}/>;
}
export type ButtonLinkProps = AnchorHTMLAttributes<HTMLAnchorElement> & {variant?: 'primary' | 'secondary'};
export function ButtonLink({className = '', variant = 'primary', ...props}: ButtonLinkProps) {
  return <a {...props} className={`button tw-button ${variant === 'secondary' ? 'secondary' : ''} ${className}`}/>;
}

type FieldBase = {label: string; hint?: ReactNode; error?: string; className?: string};
export type FieldProps = FieldBase & (
  | ({as?: 'input'} & InputHTMLAttributes<HTMLInputElement>)
  | ({as: 'textarea'} & TextareaHTMLAttributes<HTMLTextAreaElement>)
  | ({as: 'select'; options: readonly {value: string; label: string; disabled?: boolean}[]} & SelectHTMLAttributes<HTMLSelectElement>)
);
export function Field(props: FieldProps) {
  const generated = useId();
  const {label, hint, error, className = '', ...control} = props;
  const id = control.id ?? generated;
  const describedBy = [control['aria-describedby'], hint ? `${id}-hint` : '', error ? `${id}-error` : ''].filter(Boolean).join(' ') || undefined;
  const accessibility = {id, 'aria-describedby': describedBy, 'aria-invalid': error ? true as const : control['aria-invalid']};
  let input: ReactNode;
  if (control.as === 'textarea') {const {as: _, ...attributes} = control; input = <textarea {...attributes} {...accessibility}/>;}
  else if (control.as === 'select') {const {as: _, options, ...attributes} = control; input = <select {...attributes} {...accessibility}>{options.map(option => <option key={option.value} {...option}>{option.label}</option>)}</select>;}
  else {const {as: _, ...attributes} = control; input = <input {...attributes} {...accessibility}/>;}
  return <div className={`tw-field ${className}`}><label htmlFor={id}>{label}{control.required ? <span aria-hidden="true"> *</span> : null}</label>{input}{hint ? <p id={`${id}-hint`} className="tw-field-hint">{hint}</p> : null}{error ? <p id={`${id}-error`} className="tw-field-error">{error}</p> : null}</div>;
}

export type NoticeProps = {children: ReactNode; tone?: 'info' | 'success' | 'warning' | 'error'; title?: string};
export function Notice({children, tone = 'info', title}: NoticeProps) {
  return <div className="tw-notice" data-tone={tone} role={tone === 'error' ? 'alert' : 'status'}>{title ? <strong>{title}</strong> : null}<div>{children}</div></div>;
}
export type EmptyStateProps = {title: string; description?: ReactNode; action?: ReactNode};
export function EmptyState({title, description, action}: EmptyStateProps) {
  return <div className="tw-empty"><h2>{title}</h2>{description ? <p>{description}</p> : null}{action}</div>;
}

export type CoverProps = {title: string; src?: string | null; alt?: string; fit?: 'contain' | 'cover' | 'top'; loading?: 'lazy' | 'eager'};
export function Cover({title, src, alt = '', fit = 'contain', loading = 'lazy'}: CoverProps) {
  const [failed, setFailed] = useState<string | null>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const missing = !src || src === failed;
  useLayoutEffect(() => {if (canvas.current) {canvas.current.width = 0; canvas.current.height = 0;}}, [src]);
  return <div className={`cover-media sample-cover tw-cover ${missing ? 'media-missing' : ''}`} data-fit={fit}>
    <span className="media-fallback" aria-hidden="true"><span className="sample-cover-title">{title}</span></span>
    {!missing ? <><canvas className="media-backdrop" ref={canvas} aria-hidden="true" width="0" height="0"/><img className="media-main" src={src!} alt={alt} loading={loading} decoding="async" onError={() => setFailed(src!)} onLoad={event => {
      const image = event.currentTarget, decoration = canvas.current;
      if (!decoration) return;
      // Draw the already decoded source once. No pixel readback, cross-origin
      // credentials, external image proxy, second fetch or animated filter.
      decoration.width = 160; decoration.height = 90;
      const context = decoration.getContext('2d');
      if (!context) return;
      const scale = Math.max(160 / image.naturalWidth, 90 / image.naturalHeight);
      const width = image.naturalWidth * scale, height = image.naturalHeight * scale;
      context.drawImage(image, (160 - width) / 2, (90 - height) / 2, width, height);
    }}/></> : null}
  </div>;
}
export type ContentCardProps = {
  title: string; href: string; author?: string; meta?: string; description?: string;
  cover?: Omit<CoverProps, 'title'>; actions?: ReactNode;
};
export function ContentCard({title, href, author, meta, description, cover, actions}: ContentCardProps) {
  return <article className="sample-card tw-content-card"><a className="entrance-card" href={href}>
    <Cover {...cover} title={title}/><div className="sample-card-heading"><h2>{title}</h2><p className="sample-card-meta">{[author, meta].filter(Boolean).join(' · ') || <span aria-hidden="true">{'\u00a0'}</span>}</p></div><p className="entrance-description">{description || <span aria-hidden="true">{'\u00a0'}</span>}</p>
  </a>{actions ? <div className="sample-card-footer"><div className="sample-card-actions">{actions}</div></div> : null}</article>;
}
export type ContentGridProps = {children: ReactNode; className?: string};
export function ContentGrid({children, className = ''}: ContentGridProps) {
  return <div className={`course-grid tw-content-grid ${className}`}>{children}</div>;
}

export type Resource = {id: string; title: string; description?: string; href: string; actionLabel?: string; external?: boolean};
export type ResourceListProps = {resources: readonly Resource[]; label?: string};
export function ResourceList({resources, label = '相关资料'}: ResourceListProps) {
  return <ul className="tw-resources" aria-label={label}>{resources.map(resource => <li key={resource.id} className="resource-row"><svg className="icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M14 2H5v20h14V7l-5-5ZM14 2v5h5M8 12h8M8 16h6"/></svg><div className="resource-copy"><strong>{resource.title}</strong>{resource.description ? <p>{resource.description}</p> : null}</div><a className="text-link" href={resource.href} target={resource.external ? '_blank' : undefined} rel={resource.external ? 'noopener noreferrer' : undefined} aria-label={`${resource.actionLabel ?? '查看'}：${resource.title}`}>{resource.actionLabel ?? '查看'}</a></li>)}</ul>;
}

export type WorkspaceProps = {navigation: readonly NavigationItem[]; children: ReactNode; identity?: ReactNode; label?: string};
export function Workspace({navigation, children, identity, label = '工作区导航'}: WorkspaceProps) {
  return <div className="frame tw-workspace"><aside className="tw-workspace-sidebar">{identity ? <div className="tw-workspace-identity">{identity}</div> : null}<nav aria-label={label}>{navigation.map(item => <a key={item.id} href={item.href} aria-current={item.current ? 'page' : undefined}>{item.label}</a>)}</nav></aside><div className="tw-workspace-content">{children}</div></div>;
}
