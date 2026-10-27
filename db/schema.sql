-- Signal-to-Rain schema. The pipeline applies this before writing, so it must
-- stay idempotent. Each pipeline run replaces one dataset; deleting the row in
-- `datasets` removes everything that belongs to it.

CREATE TABLE IF NOT EXISTS datasets (
    id          text PRIMARY KEY,               -- e.g. 'synthetic', 'openmrg'
    meta        jsonb NOT NULL,                 -- source, region, bounds, wet/dry scores...
    grid_lat    double precision[] NOT NULL,    -- rainfall grid axes, south to north
    grid_lon    double precision[] NOT NULL,    -- west to east
    created_at  timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS links (
    dataset        text NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    id             text NOT NULL,
    site_0_lat     double precision NOT NULL,
    site_0_lon     double precision NOT NULL,
    site_1_lat     double precision NOT NULL,
    site_1_lon     double precision NOT NULL,
    length_km      real NOT NULL,
    frequency_ghz  real NOT NULL,
    polarization   text NOT NULL,
    PRIMARY KEY (dataset, id)
);

CREATE TABLE IF NOT EXISTS link_rain (
    dataset    text NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    time       timestamp NOT NULL,
    cml_id     text NOT NULL,
    rain_rate  real,                            -- mm/h, NULL when the link had no data
    wet        boolean NOT NULL,
    PRIMARY KEY (dataset, time, cml_id)
);

-- One row per time step; the frame is float32, row-major (lat, lon), NaN = no data
CREATE TABLE IF NOT EXISTS rain_grid (
    dataset    text NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    time       timestamp NOT NULL,
    rain_rate  bytea NOT NULL,
    PRIMARY KEY (dataset, time)
);

CREATE TABLE IF NOT EXISTS gauges (
    dataset  text NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    id       text NOT NULL,
    lat      double precision NOT NULL,
    lon      double precision NOT NULL,
    PRIMARY KEY (dataset, id)
);

CREATE TABLE IF NOT EXISTS gauge_rain (
    dataset   text NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    gauge_id  text NOT NULL,
    time      timestamp NOT NULL,
    gauge     real,                             -- measured, mm/h
    estimate  real,                             -- from links at the gauge location, mm/h
    PRIMARY KEY (dataset, gauge_id, time)
);

CREATE TABLE IF NOT EXISTS hotspots (
    dataset        text NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    id             text NOT NULL,
    name           text NOT NULL,
    vulnerability  real NOT NULL,
    lat            double precision NOT NULL,
    lon            double precision NOT NULL,
    PRIMARY KEY (dataset, id)
);

CREATE TABLE IF NOT EXISTS flood_risk (
    dataset     text NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    time        timestamp NOT NULL,
    hotspot_id  text NOT NULL,
    rain_rate   real NOT NULL,
    acc_1h      real NOT NULL,                  -- mm in the last hour
    acc_3h      real NOT NULL,                  -- mm in the last 3 hours
    risk        real NOT NULL,                  -- 0 to 1
    level       text NOT NULL CHECK (level IN ('low', 'medium', 'high')),
    PRIMARY KEY (dataset, time, hotspot_id)
);

CREATE TABLE IF NOT EXISTS alerts (
    dataset     text NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
    time        timestamp NOT NULL,
    hotspot_id  text NOT NULL,
    name        text NOT NULL,
    level       text NOT NULL,
    acc_1h      real NOT NULL,
    message     text NOT NULL
);
CREATE INDEX IF NOT EXISTS alerts_dataset_time ON alerts (dataset, time);
