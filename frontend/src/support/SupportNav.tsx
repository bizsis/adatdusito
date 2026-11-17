import React, { useEffect, useRef } from "react";
import { BookOpen, ChevronDown, LifeBuoy } from "lucide-react";
export function SupportNav({ active }: { active: boolean }) {
  const menu = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    if (active && menu.current) menu.current.open = true;
  }, [active]);
  return (
    <details ref={menu} className="support-menu">
      <summary>
        <LifeBuoy size={19} aria-hidden="true" />
        Támogatás
        <ChevronDown className="support-chevron" size={15} aria-hidden="true" />
      </summary>
      <a
        href="#/segedlet"
        aria-current={active ? "page" : undefined}
        className={active ? "active" : ""}
      >
        <BookOpen size={17} aria-hidden="true" />
        Segédlet
      </a>
    </details>
  );
}
