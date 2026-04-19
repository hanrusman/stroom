FROM node:20-alpine

WORKDIR /app

# We need git for some npm installs occasionally, and bash for scripts
RUN apk add --no-cache bash git

EXPOSE 3000
ENV PORT=3000
ENV HOST=0.0.0.0

# Copy the init script
COPY init.sh /usr/local/bin/init.sh
RUN chmod +x /usr/local/bin/init.sh

ENTRYPOINT ["/usr/local/bin/init.sh"]
