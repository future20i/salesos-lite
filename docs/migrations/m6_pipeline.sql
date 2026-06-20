-- m6_pipeline.sql — Pipeline data model migration
-- Auto-created tables: opportunities, followup_items, followup_events, knowledge_entries
-- Manual ALTER: leads.opportunity_id, messages.followup_id, MessageDirection SYSTEM value

-- New enum types (Base.metadata.create_all handles these if created during startup)
DO $$ BEGIN
    CREATE TYPE opportunitystage AS ENUM (
        'lead_validation','needs_confirmation','technical_exchange',
        'quotation_negotiation','contract','won','lost','shelved'
    );
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE followupstatus AS ENUM ('todo','in_progress','pending_review','done');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

DO $$ BEGIN
    CREATE TYPE reviewlevel AS ENUM ('routine','commercial','critical');
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- Extend existing tables (Base.metadata.create_all does NOT add columns to existing tables)
ALTER TABLE leads ADD COLUMN IF NOT EXISTS opportunity_id UUID REFERENCES opportunities(id);
ALTER TABLE messages ADD COLUMN IF NOT EXISTS followup_id UUID REFERENCES followup_items(id);

-- MessageDirection enum: add SYSTEM value if not exists
ALTER TYPE messagedirection ADD VALUE IF NOT EXISTS 'system';
