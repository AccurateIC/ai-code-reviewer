#!/bin/bash
set -e

echo "🚀 AI Code Reviewer Setup"
echo "=========================="

# Check prerequisites
command -v docker >/dev/null 2>&1 || { echo "❌ Docker required but not installed. Aborting." >&2; exit 1; }
command -v docker compose >/dev/null 2>&1 || { echo "❌ Docker Compose required but not installed. Aborting." >&2; exit 1; }

# Create environment file if not exists
if [ ! -f .env ]; then
    echo "📝 Creating .env file..."
    cat > .env << EOF
# GitHub Configuration
GITHUB_TOKEN=your_github_personal_access_token_here
WEBHOOK_SECRET=your_webhook_secret_here

# Optional: GitHub App Mode
# GITHUB_APP_ID=your_app_id
# GITHUB_PRIVATE_KEY=your_private_key

# Ollama Configuration
OLLAMA_MODEL=qwen2.5-coder:latest

# Review Behavior
AUTO_APPROVE=false

# Optional: Ngrok for development
# NGROK_AUTH_TOKEN=your_ngrok_token
EOF
    echo "⚠️  Please edit .env file with your GitHub credentials"
    exit 1
fi

# Pull and start services
echo "🐳 Starting services..."
docker compose up -d ollama
echo "⏳ Waiting for Ollama to start..."
sleep 10

# Pull the model
echo "🤖 Downloading Qwen2.5-Coder model (this may take a while)..."
docker compose exec -T ollama ollama pull qwen2.5-coder:7b

# Start the reviewer
echo "🔍 Starting AI Reviewer..."
docker compose up -d reviewer

echo ""
echo "✅ Setup complete!"
echo ""
echo "Next steps:"
echo "1. Configure GitHub webhook to point to: http://your-server:8000/webhook/github"
echo "2. Test with: curl http://localhost:8000/health"
echo "3. View logs: docker compose logs -f reviewer"
echo ""
echo "For local development with ngrok:"
echo "   docker compose --profile dev up -d"
