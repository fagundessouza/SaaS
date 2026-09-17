-- O usuario POSTGRES_USER do docker-entrypoint (licitacoes) e criado como SUPERUSER.
-- Superusuario ignora Row-Level Security incondicionalmente, mesmo com FORCE ROW LEVEL
-- SECURITY habilitado na tabela (ver docs/SECURITY_MODEL.md e ADR-0002) — por isso a aplicacao
-- em runtime NUNCA deve se conectar como o usuario de bootstrap. Este script cria um papel
-- separado, sem privilegios de superusuario, usado pela API e pelo worker; `licitacoes`
-- continua existindo apenas para rodar migrations (DDL).

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'app_runtime') THEN
        CREATE ROLE app_runtime LOGIN PASSWORD 'app_runtime_dev_password'
            NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
    END IF;
END
$$;

GRANT CONNECT ON DATABASE licitacoes TO app_runtime;
GRANT USAGE ON SCHEMA public TO app_runtime;

-- Tabelas ja existentes (caso o script rode apos alguma migration ter criado algo)
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO app_runtime;

-- Tabelas que 'licitacoes' vier a criar no futuro (toda migration roda como 'licitacoes')
ALTER DEFAULT PRIVILEGES FOR ROLE licitacoes IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO app_runtime;
