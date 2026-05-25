# Owner: Charbel

FROM pgvector/pgvector:pg16

COPY init.sql /docker-entrypoint-initdb.d/01_init.sql
COPY rls_policies.sql /docker-entrypoint-initdb.d/02_rls_policies.sql
