-- PostgreSQL schema for the monthly party-control lookup.
CREATE SCHEMA IF NOT EXISTS mts;

CREATE TABLE IF NOT EXISTS mts.party_control (
    year integer NOT NULL,
    month integer NOT NULL CHECK (month BETWEEN 1 AND 12),
    president_name text NOT NULL,
    president_party text NOT NULL CHECK (president_party IN ('Democrat', 'Republican')),
    house_majority_party text NOT NULL CHECK (house_majority_party IN ('Democrat', 'Republican')),
    senate_majority_party text NOT NULL CHECK (senate_majority_party IN ('Democrat', 'Republican')),
    PRIMARY KEY (year, month)
);
