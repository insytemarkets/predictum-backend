# Predictum Deployment Guide

## Backend Setup (Render)

### 1. Create Supabase Project
1. Go to https://supabase.com
2. Create new project
3. Run `database/schema.sql` in SQL Editor
4. Get your project URL and service role key

### 2. Deploy Workers to Render

Create 2 Background Workers on Render (consolidated to save costs):

#### Worker 1: Data Worker (High Frequency)
- **Name**: `predictum-data-worker`
- **Command**: `python main.py data-worker`
- **What it does**: 
  - Scans markets every 30 seconds
  - Scans order books every 10 seconds
- **Environment Variables**:
  - `SUPABASE_URL`: Your Supabase URL
  - `SUPABASE_SERVICE_ROLE_KEY`: Your service role key
- **Build Command**: `pip install -r requirements.txt`

#### Worker 2: Analysis Worker (Lower Frequency)
- **Name**: `predictum-analysis-worker`
- **Command**: `python main.py analysis-worker`
- **What it does**:
  - Detects opportunities every 60 seconds
  - Aggregates stats every 5 minutes
- **Environment Variables**: Same as above

### 3. GitHub Repository Setup

1. Create new GitHub repo (e.g., `predictum-backend`)
2. Push backend code:
```bash
cd predictum-markets/backend
git init
git add .
git commit -m "Initial backend setup"
git remote add origin <your-repo-url>
git push -u origin main
```

3. Connect Render workers to GitHub repo
4. Enable auto-deploy

## Frontend Setup (Vercel)

### 1. Environment Variables

Add to Vercel project settings:
- `VITE_SUPABASE_URL`: Your Supabase project URL
- `VITE_SUPABASE_ANON_KEY`: Your Supabase anon/public key (NOT service role)

### 2. Enable Supabase Realtime

In Supabase Dashboard:
1. Go to Database → Replication
2. Enable replication for tables:
   - `markets`
   - `opportunities`
   - `order_books`
   - `prices`

### 3. Update Frontend

The frontend is already set up to consume data from Supabase. Once workers are running and populating data, the frontend will automatically display real data.

## Testing Locally

### Backend
```bash
cd backend
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Supabase credentials
python main.py market-scanner  # Test individual worker
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## Monitoring

- **Render Dashboard**: Monitor worker logs and status
- **Supabase Dashboard**: Monitor database, check data is being inserted
- **Vercel Dashboard**: Monitor frontend deployments

## Next Steps

1. ✅ Backend API client implemented
2. ✅ Workers implemented
3. ✅ Frontend Supabase integration ready
4. ⏳ Deploy workers to Render
5. ⏳ Set up Supabase project
6. ⏳ Configure environment variables
7. ⏳ Test end-to-end data flow

