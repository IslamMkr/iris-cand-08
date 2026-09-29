GRANT USAGE ON SCHEMA iris_staging_nrw TO contributor_nrw;
GRANT USAGE ON SCHEMA iris_staging_peat TO contributor_peat;
GRANT SELECT, INSERT ON iris_staging_nrw.features TO contributor_nrw;
GRANT SELECT, INSERT ON iris_staging_peat.features TO contributor_peat;

GRANT USAGE ON SCHEMA iris_staging_nrw, iris_staging_peat, iris_ops TO promoter;
GRANT SELECT ON iris_staging_nrw.features, iris_staging_peat.features TO promoter;

GRANT USAGE ON SCHEMA iris_staging_nrw, iris_staging_peat, iris_core
  TO iris_promote_executor;
GRANT SELECT ON iris_staging_nrw.features, iris_staging_peat.features
  TO iris_promote_executor;
GRANT INSERT ON iris_core.features TO iris_promote_executor;
-- An explicit ON CONFLICT target requires SELECT on its indexed columns.
GRANT SELECT (country_code, dataset, source_id) ON iris_core.features
  TO iris_promote_executor;

REVOKE ALL ON FUNCTION iris_ops.promote(text, text, text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION iris_ops.promote(text, text, text) TO promoter;

GRANT USAGE ON SCHEMA iris_api TO app_readonly;
GRANT SELECT ON iris_api.candidates TO app_readonly;
