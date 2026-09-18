"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

// Navegação MVP definida em docs/UX_AND_ASSISTANT_SPEC.md: "Visão Geral · Radar · Análises ·
// Minha Empresa · Documentos · Inteligência Competitiva · Jurídico" (Assistente é um componente
// flutuante global, não um item de navegação — ver components/AssistantButton.tsx).
const LINKS = [
  { href: "/", label: "Visão Geral" },
  { href: "/radar", label: "Radar" },
  { href: "/analises", label: "Análises" },
  { href: "/minha-empresa", label: "Minha Empresa" },
  { href: "/documentos", label: "Documentos" },
  { href: "/inteligencia-competitiva", label: "Inteligência Competitiva" },
  { href: "/juridico", label: "Jurídico" },
];

export function NavLinks() {
  const pathname = usePathname();

  return (
    <>
      {LINKS.map((link) => {
        const active = link.href === "/" ? pathname === "/" : pathname.startsWith(link.href);
        return (
          <Link
            key={link.href}
            href={link.href}
            className={`rounded-md px-3 py-1.5 text-sm font-medium ${
              active ? "bg-slate-900 text-white" : "text-slate-600 hover:bg-slate-100"
            }`}
          >
            {link.label}
          </Link>
        );
      })}
    </>
  );
}
