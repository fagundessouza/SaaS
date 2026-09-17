# SaaS — Fluxo de trabalho Git

O usuário (Lucas) trabalha neste projeto em dois computadores diferentes (casa e trabalho), alternando várias vezes por dia. Não usa nenhuma ferramenta de sync além do Git, então a branch `dev` é o "estado compartilhado" entre as duas máquinas.

**Sempre que uma sessão começar a trabalhar neste repositório:**
1. Rodar `git checkout dev` (se não estiver nela) e `git pull origin dev` **antes** de ler código ou fazer qualquer alteração — para continuar exatamente de onde ficou na última sessão (possivelmente em outra máquina).
2. Fazer o trabalho pedido normalmente.
3. **Antes de encerrar a sessão** (ou sempre que fizer sentido, ex: após completar uma tarefa), commitar e dar `git push origin dev` das alterações — para que a próxima sessão (nesta ou em outra máquina) já encontre o trabalho atualizado.

Não é necessário perguntar permissão para `pull`/`push` na branch `dev` neste fluxo de rotina — já é o processo combinado. Se houver conflito de merge, avisar o usuário e resolver junto (não sobrescrever nada sozinho).

Quando o trabalho na `dev` estiver pronto/testado, perguntar ao usuário antes de mesclar (`merge`) na `main`.
