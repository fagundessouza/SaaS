import { redirect } from "next/navigation";

import { AssistantButton } from "@/components/AssistantButton";
import { NavLinks } from "@/components/NavLinks";
import { LogoutButton } from "@/components/LogoutButton";
import { pageFetch } from "@/lib/api";
import { getSession } from "@/lib/session";
import type { CurrentUser } from "@/lib/types";

export default async function AppLayout({ children }: { children: React.ReactNode }) {
  // Checa o cookie primeiro (sem chamada de rede) e redireciona antes de qualquer fetch — sem
  // isto, o layout e as páginas filhas (Server Components independentes) disparam suas próprias
  // chamadas à API em paralelo antes do redirect do layout "vencer". pageFetch (ver lib/api.ts)
  // cobre o resto: toda página usa redirect() em vez de deixar SessionExpiredError propagar sem
  // captura, então não sobra erro não tratado no log mesmo nesse cenário concorrente.
  const session = await getSession();
  if (!session) redirect("/login");

  const user = await pageFetch<CurrentUser>("/v1/users/me");

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <span className="text-lg font-semibold">Licitações</span>
          <nav className="flex items-center gap-1">
            <NavLinks />
          </nav>
          <div className="flex items-center gap-3 text-sm text-slate-600">
            <span>{user.email}</span>
            <LogoutButton />
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 px-6 py-8">{children}</main>

      <AssistantButton />
    </div>
  );
}
