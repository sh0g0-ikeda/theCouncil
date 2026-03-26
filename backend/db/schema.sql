CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE agents (
  id VARCHAR PRIMARY KEY,
  display_name VARCHAR NOT NULL,
  label VARCHAR NOT NULL,
  persona_json JSONB NOT NULL,
  vector INTEGER[10] NOT NULL,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  x_id VARCHAR UNIQUE,
  email VARCHAR UNIQUE,
  role VARCHAR NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
  plan VARCHAR NOT NULL DEFAULT 'free' CHECK (plan IN ('free', 'pro', 'ultra')),
  monthly_thread_count INTEGER NOT NULL DEFAULT 0,
  thread_usage_month DATE NOT NULL DEFAULT DATE_TRUNC('month', NOW())::date,
  warning_count INTEGER NOT NULL DEFAULT 0,
  is_banned BOOLEAN NOT NULL DEFAULT FALSE,
  stripe_customer_id VARCHAR,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE email_login_tokens (
  email VARCHAR NOT NULL,
  token_hash VARCHAR NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  attempt_count INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (email, token_hash)
);

CREATE TABLE threads (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id UUID REFERENCES users(id),
  topic TEXT NOT NULL,
  topic_tags TEXT[] NOT NULL DEFAULT '{}',
  agent_ids VARCHAR[] NOT NULL,
  state VARCHAR NOT NULL DEFAULT 'running' CHECK (state IN ('running', 'paused', 'completed')),
  visibility VARCHAR NOT NULL DEFAULT 'public' CHECK (visibility IN ('public', 'private')),
  max_posts INTEGER NOT NULL DEFAULT 50,
  current_phase INTEGER NOT NULL DEFAULT 1,
  speed_mode VARCHAR NOT NULL DEFAULT 'normal' CHECK (speed_mode IN ('normal', 'fast', 'instant', 'paused')),
  script_json JSONB,
  hidden_at TIMESTAMPTZ,
  locked_at TIMESTAMPTZ,
  deleted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE posts (
  id SERIAL,
  thread_id UUID REFERENCES threads(id) ON DELETE CASCADE,
  agent_id VARCHAR REFERENCES agents(id),
  user_id UUID REFERENCES users(id),
  reply_to INTEGER,
  content TEXT NOT NULL,
  stance VARCHAR CHECK (stance IN ('disagree', 'agree', 'supplement', 'shift', 'facilitate')),
  focus_axis VARCHAR,
  is_facilitator BOOLEAN NOT NULL DEFAULT FALSE,
  token_usage INTEGER NOT NULL DEFAULT 0,
  hidden_at TIMESTAMPTZ,
  deleted_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (thread_id, id)
);

CREATE TABLE chunks (
  id SERIAL PRIMARY KEY,
  agent_id VARCHAR REFERENCES agents(id) ON DELETE CASCADE,
  topic VARCHAR NOT NULL,
  tags TEXT[] NOT NULL DEFAULT '{}',
  text TEXT NOT NULL,
  embedding VECTOR(1536)
);

CREATE TABLE reports (
  id SERIAL PRIMARY KEY,
  thread_id UUID REFERENCES threads(id),
  post_id INTEGER,
  reporter_id UUID REFERENCES users(id),
  reason VARCHAR NOT NULL CHECK (reason IN ('hate', 'violence', 'defamation', 'crime', 'other')),
  status VARCHAR NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'resolved', 'dismissed')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE thread_shares (
  user_id UUID REFERENCES users(id) ON DELETE CASCADE,
  thread_id UUID REFERENCES threads(id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (user_id, thread_id)
);

-- One vote per user per thread; agent_id = who they thought was sharpest
CREATE TABLE thread_votes (
  thread_id UUID NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
  user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  agent_id VARCHAR NOT NULL REFERENCES agents(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  PRIMARY KEY (thread_id, user_id)
);

CREATE INDEX chunks_tags_idx ON chunks USING gin(tags);
CREATE INDEX chunks_fts_idx ON chunks USING gin(to_tsvector('simple', text));
CREATE INDEX email_login_tokens_expires_idx ON email_login_tokens(expires_at);
CREATE INDEX posts_thread_created_idx ON posts(thread_id, created_at);
CREATE INDEX threads_state_created_idx ON threads(state, created_at DESC);
CREATE INDEX reports_status_created_idx ON reports(status, created_at DESC);
