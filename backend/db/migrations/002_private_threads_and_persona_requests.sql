-- Add private thread quota tracking to users
ALTER TABLE users
  ADD COLUMN IF NOT EXISTS monthly_private_thread_count INTEGER NOT NULL DEFAULT 0;

-- Persona request submissions (anyone can submit, admin reviews)
CREATE TABLE IF NOT EXISTS persona_requests (
  id SERIAL PRIMARY KEY,
  requester_id UUID REFERENCES users(id) ON DELETE SET NULL,
  person_name VARCHAR NOT NULL,
  description TEXT NOT NULL,
  status VARCHAR NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'in_progress', 'done', 'rejected')),
  admin_note TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS persona_requests_status_idx ON persona_requests(status, created_at DESC);
