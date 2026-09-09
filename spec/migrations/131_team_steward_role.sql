-- New grants use member/steward. Preserve historical owner rows rather than
-- silently converting an old offer or membership into new mutation authority.
-- Application grant paths reject new owner values and pending owner acceptance.
ALTER TABLE team_members DROP CONSTRAINT IF EXISTS team_members_role_check;
ALTER TABLE team_members ADD CONSTRAINT team_members_role_check
    CHECK (role IN ('member', 'steward', 'owner'));

ALTER TABLE ory_enrollment_teams DROP CONSTRAINT IF EXISTS ory_enrollment_teams_role_check;
ALTER TABLE ory_enrollment_teams ADD CONSTRAINT ory_enrollment_teams_role_check
    CHECK (role IN ('member', 'steward', 'owner'));
