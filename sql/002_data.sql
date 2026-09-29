SET LOCAL ROLE iris_owner;

CREATE TABLE iris_staging_nrw.features (
  country_code text NOT NULL CHECK (country_code ~ '^[A-Z]{2}$'),
  source_id text NOT NULL CHECK (length(btrim(source_id)) > 0),
  -- A geometry(...,4326) typmod silently labels SRID=0 input as 4326. Explicit
  -- checks preserve the contract: unknown CRS must be rejected, never invented.
  geom public.geometry NOT NULL
    CHECK (public.ST_SRID(geom) = 4326)
    CHECK (public.ST_GeometryType(geom) = 'ST_MultiPolygon')
    CHECK (public.ST_NDims(geom) = 2)
    CHECK (NOT public.ST_IsEmpty(geom) AND public.ST_IsValid(geom)),
  source_date date NOT NULL,
  uncertainty text NOT NULL CHECK (length(btrim(uncertainty)) > 0),
  PRIMARY KEY (country_code, source_id)
);

CREATE TABLE iris_staging_peat.features
  (LIKE iris_staging_nrw.features INCLUDING ALL);

CREATE TABLE iris_core.features (
  LIKE iris_staging_nrw.features INCLUDING CONSTRAINTS,
  dataset text NOT NULL CHECK (dataset IN ('nrw', 'peat')),
  PRIMARY KEY (country_code, dataset, source_id)
);

CREATE VIEW iris_api.candidates AS
  SELECT country_code, dataset, source_id, geom, source_date, uncertainty
  FROM iris_core.features;

COMMENT ON VIEW iris_api.candidates IS
  'Published feature records available to read-only application clients.';

CREATE FUNCTION iris_ops.promote(
  p_dataset text, p_country_code text, p_source_id text
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER
SET search_path = pg_catalog, pg_temp
AS $$
DECLARE
  staged record;
  inserted integer;
BEGIN
  IF p_dataset IS NULL OR p_dataset NOT IN ('nrw', 'peat')
     OR p_country_code IS NULL OR p_country_code !~ '^[A-Z]{2}$'
     OR p_source_id IS NULL OR length(btrim(p_source_id)) = 0 THEN
    RAISE EXCEPTION 'Expected dataset nrw/peat, uppercase country code, and source ID'
      USING ERRCODE = '22023';
  END IF;

  -- No caller-controlled identifiers or dynamic SQL. Contributors cannot modify
  -- an existing row, so selecting a specific key identifies the reviewed data.
  IF p_dataset = 'nrw' THEN
    SELECT country_code, source_id, geom, source_date, uncertainty INTO staged
    FROM iris_staging_nrw.features
    WHERE country_code = p_country_code AND source_id = p_source_id;
  ELSE
    SELECT country_code, source_id, geom, source_date, uncertainty INTO staged
    FROM iris_staging_peat.features
    WHERE country_code = p_country_code AND source_id = p_source_id;
  END IF;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'Staging record not found' USING ERRCODE = 'P0002';
  END IF;

  INSERT INTO iris_core.features
    (country_code, dataset, source_id, geom, source_date, uncertainty)
  VALUES
    (staged.country_code, p_dataset, staged.source_id, staged.geom,
     staged.source_date, staged.uncertainty)
  ON CONFLICT (country_code, dataset, source_id) DO NOTHING;
  GET DIAGNOSTICS inserted = ROW_COUNT;
  RETURN inserted;
END;
$$;

RESET ROLE;
ALTER FUNCTION iris_ops.promote(text, text, text) OWNER TO iris_promote_executor;
