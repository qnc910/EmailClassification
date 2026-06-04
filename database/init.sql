CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE NOT NULL,
    password_hash VARCHAR(255) NOT NULL,
    role VARCHAR(20) DEFAULT 'user',
    last_active_at TIMESTAMP DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS emails (
    id SERIAL PRIMARY KEY,
    sender VARCHAR(255),
    recipient VARCHAR(255),
    subject TEXT,
    body TEXT,
    category VARCHAR(50) DEFAULT 'inbox',
    subcategory VARCHAR(50) DEFAULT NULL,
    is_read BOOLEAN DEFAULT FALSE,
    deleted_at TIMESTAMP DEFAULT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_emails_recipient_category_created ON emails (recipient, category, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_emails_sender_created ON emails (sender, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_emails_created_at ON emails (created_at DESC);

CREATE TABLE IF NOT EXISTS email_stats (
    recipient VARCHAR(255) NOT NULL,
    category VARCHAR(50) NOT NULL,
    subcategory VARCHAR(50) DEFAULT '',
    count INT DEFAULT 0,
    PRIMARY KEY (recipient, category, subcategory)
);

CREATE INDEX IF NOT EXISTS idx_email_stats_recipient ON email_stats (recipient);

CREATE OR REPLACE FUNCTION update_email_stats()
RETURNS TRIGGER AS $$
DECLARE
    v_recipient VARCHAR(255);
    v_category VARCHAR(50);
    v_subcategory VARCHAR(50);
BEGIN
    IF (TG_OP = 'INSERT') THEN
        v_recipient := NEW.recipient;
        v_category := NEW.category;
        v_subcategory := COALESCE(NEW.subcategory, '');
        
        INSERT INTO email_stats (recipient, category, subcategory, count)
        VALUES (v_recipient, v_category, v_subcategory, 1)
        ON CONFLICT (recipient, category, subcategory)
        DO UPDATE SET count = email_stats.count + 1;
    END IF;
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_emails_stats ON emails;
CREATE TRIGGER trg_emails_stats
AFTER INSERT ON emails
FOR EACH ROW
EXECUTE FUNCTION update_email_stats();

