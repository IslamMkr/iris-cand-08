-- Apply once, as the administrator, in this project's dedicated cluster.
-- Bootstrap includes this file in its transaction. For an existing database,
-- use psql --single-transaction --set=ON_ERROR_STOP=1 --file=sql/004_hardening.sql.
\set ON_ERROR_STOP on

-- Login roles are cluster-wide. PUBLIC access to another database would let
-- them bypass the intended database boundary, even when iris itself is locked.
DO $$
DECLARE database_name text;
BEGIN
  FOR database_name IN SELECT datname FROM pg_database
  LOOP
    EXECUTE format('REVOKE ALL ON DATABASE %I FROM PUBLIC', database_name);
  END LOOP;
END;
$$;

-- SRID and topological validity do not validate longitude/latitude units.
-- Validate existing rows too: a failed check rolls back the entire migration.
ALTER TABLE iris_staging_nrw.features
  ADD CONSTRAINT features_geom_bounds_check CHECK (
    public.ST_XMin(geom::public.box3d) >= -180
    AND public.ST_XMax(geom::public.box3d) <= 180
    AND public.ST_YMin(geom::public.box3d) >= -90
    AND public.ST_YMax(geom::public.box3d) <= 90
  );
ALTER TABLE iris_staging_peat.features
  ADD CONSTRAINT features_geom_bounds_check CHECK (
    public.ST_XMin(geom::public.box3d) >= -180
    AND public.ST_XMax(geom::public.box3d) <= 180
    AND public.ST_YMin(geom::public.box3d) >= -90
    AND public.ST_YMax(geom::public.box3d) <= 90
  );
ALTER TABLE iris_core.features
  ADD CONSTRAINT features_geom_bounds_check CHECK (
    public.ST_XMin(geom::public.box3d) >= -180
    AND public.ST_XMax(geom::public.box3d) <= 180
    AND public.ST_YMin(geom::public.box3d) >= -90
    AND public.ST_YMax(geom::public.box3d) <= 90
  );
