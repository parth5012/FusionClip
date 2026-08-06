FROM node:18-alpine

WORKDIR /app

# Install dependencies first (leverage Docker build cache)
COPY package*.json ./
RUN npm install

# Copy application source
COPY . .

# Expose port (default 3000 for next dev/start)
EXPOSE 3000

# Set environment
ENV PORT 3000

# Starting dev server
CMD ["npm", "run", "dev"]
