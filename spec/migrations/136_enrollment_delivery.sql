-- Whether an invitation was ever sent to the person it names.
--
-- Until now an enrollment was issued, redeemed or revoked, and nothing recorded delivery
-- at all. The UI shows the issued link, which reads as "we have invited them" — and the
-- invitation only exists in a browser somebody happened to have open. An administrator who
-- closes that tab has invited nobody and has no way to find out.
--
-- The default is not_attempted, deliberately. Backfilling anything else would assert that
-- every invitation already issued had been delivered, which nothing checked and nothing
-- did. An issued link is not an email.
ALTER TABLE ory_enrollments
    ADD COLUMN IF NOT EXISTS delivery_state TEXT NOT NULL DEFAULT 'not_attempted';
ALTER TABLE ory_enrollments DROP CONSTRAINT IF EXISTS ory_enrollments_delivery_state_check;
ALTER TABLE ory_enrollments ADD CONSTRAINT ory_enrollments_delivery_state_check
    CHECK (delivery_state IN ('not_attempted', 'pending', 'delivered', 'failed'));

-- Bounded retry needs a count that survives a restart. A retry loop that keeps its attempts
-- in memory retries forever after a crash, against a mail server that is refusing for a
-- reason that has not changed.
ALTER TABLE ory_enrollments
    ADD COLUMN IF NOT EXISTS delivery_attempts INTEGER NOT NULL DEFAULT 0;
ALTER TABLE ory_enrollments DROP CONSTRAINT IF EXISTS ory_enrollments_delivery_attempts_check;
ALTER TABLE ory_enrollments ADD CONSTRAINT ory_enrollments_delivery_attempts_check
    CHECK (delivery_attempts >= 0);

-- Sanitized, and never the invitation secret. This column is read by an administrator
-- looking at a list of people they invited; a token in it would be a token in every backup
-- and every screenshot of that screen.
ALTER TABLE ory_enrollments
    ADD COLUMN IF NOT EXISTS delivery_detail TEXT NOT NULL DEFAULT '';
ALTER TABLE ory_enrollments DROP CONSTRAINT IF EXISTS ory_enrollments_delivery_detail_check;
ALTER TABLE ory_enrollments ADD CONSTRAINT ory_enrollments_delivery_detail_check
    CHECK (length(delivery_detail) <= 2000);

ALTER TABLE ory_enrollments
    ADD COLUMN IF NOT EXISTS delivery_updated_at TIMESTAMPTZ;

-- A state that claims an outcome has to say when it was reached. not_attempted and pending
-- are the two that have not reached one.
ALTER TABLE ory_enrollments DROP CONSTRAINT IF EXISTS ory_enrollments_delivery_timing_check;
ALTER TABLE ory_enrollments ADD CONSTRAINT ory_enrollments_delivery_timing_check
    CHECK ((delivery_state IN ('delivered', 'failed')) = (delivery_updated_at IS NOT NULL));
