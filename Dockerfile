FROM python:3.11-slim

# Install LibreOffice (for PPT conversion) and Poppler (for PDF processing)
RUN apt-get update && apt-get install -y \
    libreoffice \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Set permissions for the startup script
RUN chmod +x entrypoint.sh

# Start the application
CMD ["./entrypoint.sh"]