FROM postgres:16-alpine

COPY backend/scripts/openwebui-db-init.sh /scripts/openwebui-db-init.sh
RUN chmod +x /scripts/openwebui-db-init.sh

ENTRYPOINT ["/bin/sh", "/scripts/openwebui-db-init.sh"]
