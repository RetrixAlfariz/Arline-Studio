import { Fragment, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";

export interface Crumb {
  label: string;
  onClick?: () => void;
}

/** Notion-style page top bar: breadcrumb trail on the left, page actions on the right. */
export function PageHeader({ crumbs, actions }: { crumbs: Crumb[]; actions?: ReactNode }) {
  return (
    <header className="page-header">
      <nav className="page-crumbs" aria-label="Breadcrumb">
        {crumbs.map((crumb, index) => (
          <Fragment key={`${crumb.label}-${index}`}>
            {index > 0 && <ChevronRight size={13} aria-hidden="true" />}
            {crumb.onClick && index < crumbs.length - 1
              ? <button onClick={crumb.onClick}>{crumb.label}</button>
              : <span aria-current={index === crumbs.length - 1 ? "page" : undefined}>{crumb.label}</span>}
          </Fragment>
        ))}
      </nav>
      {actions ? <div className="page-actions">{actions}</div> : null}
    </header>
  );
}
