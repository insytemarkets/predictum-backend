# GitHub Repository Setup

## Create New Repository

1. Go to https://github.com/new
2. Repository name: `predictum-backend`
3. Description: "Backend workers for Predictum - Polymarket data collection and analysis"
4. Set to **Private** (or Public if you prefer)
5. **DO NOT** initialize with README, .gitignore, or license (we already have these)
6. Click "Create repository"

## Push Code to GitHub

After creating the repo, GitHub will show you commands. Use these:

```bash
cd C:\Users\avery\OneDrive\Desktop\Predictum\predictum-markets\backend

# Add remote (replace YOUR_USERNAME with your GitHub username)
git remote add origin https://github.com/YOUR_USERNAME/predictum-backend.git

# Push to GitHub
git branch -M main
git push -u origin main
```

## Connect to Render

1. Go to Render Dashboard: https://dashboard.render.com
2. Click "New +" → "Background Worker"
3. Connect your GitHub account if not already connected
4. Select repository: `predictum-backend`
5. Configure:
   - **Name**: `predictum-data-worker`
   - **Command**: `python main.py data-worker`
   - **Environment**: Python 3
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py data-worker`
6. Add Environment Variables:
   - `SUPABASE_URL`: Your Supabase project URL
   - `SUPABASE_SERVICE_ROLE_KEY`: Your Supabase service role key
7. Click "Create Background Worker"

Repeat for the second worker:
- **Name**: `predictum-analysis-worker`
- **Command**: `python main.py analysis-worker`

## Verify

Once deployed, check the logs in Render to ensure workers are running correctly.

