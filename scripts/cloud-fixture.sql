-- ONLY for the isolated cloud test MySQL, never for a VPS.
CREATE DATABASE adatdusito_dev;
CREATE DATABASE pinfo_db;
CREATE TABLE pinfo_db.emag_categories (id INT PRIMARY KEY);
CREATE TABLE pinfo_db.emag_category_parameters (id INT PRIMARY KEY);
CREATE TABLE pinfo_db.emag_parameter_values (id INT PRIMARY KEY);
CREATE USER 'app'@'%' IDENTIFIED BY '{password}';
CREATE USER 'ref'@'%' IDENTIFIED BY '{password}';
GRANT ALL ON adatdusito_dev.* TO 'app'@'%';
GRANT SELECT ON pinfo_db.* TO 'ref'@'%';
