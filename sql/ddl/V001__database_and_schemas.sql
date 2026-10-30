-- Database and medallion schemas. Idempotent: safe to re-run.
CREATE DATABASE IF NOT EXISTS {{ database }}
    COMMENT = 'SkyPoints loyalty pipeline';

CREATE SCHEMA IF NOT EXISTS {{ database }}.BRONZE
    COMMENT = 'Raw feeds exactly as received. Append-only, never updated';
CREATE SCHEMA IF NOT EXISTS {{ database }}.SILVER
    COMMENT = 'Typed, validated, de-duplicated data and per-country member tables';
CREATE SCHEMA IF NOT EXISTS {{ database }}.GOLD
    COMMENT = 'Business-ready, history-aware tables';
CREATE SCHEMA IF NOT EXISTS {{ database }}.META
    COMMENT = 'Operational logs: file loads and pipeline runs';
