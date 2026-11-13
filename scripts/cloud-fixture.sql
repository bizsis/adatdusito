-- SYNTHETIC DATA ONLY: executed exclusively by the isolated cloud MySQL container.
-- Never run this fixture against a VPS or an existing reference database.
SET NAMES utf8mb4;
CREATE DATABASE adatdusito_dev CHARACTER SET utf8mb4;
CREATE DATABASE pinfo_db CHARACTER SET utf8mb4;
CREATE TABLE pinfo_db.emag_categories (
 id INT PRIMARY KEY, emag_category_id INT NOT NULL UNIQUE, name VARCHAR(255) NOT NULL,
 parent_id INT NULL, is_allowed BOOLEAN NULL, is_ean_mandatory BOOLEAN NULL,
 is_warranty_mandatory BOOLEAN NULL, raw_json JSON NULL, INDEX idx_parent_id(parent_id)
);
CREATE TABLE pinfo_db.emag_category_parameters (
 id INT PRIMARY KEY, category_id INT NOT NULL, emag_parameter_id INT NOT NULL,
 name VARCHAR(255) NOT NULL, type_id INT NULL, display_order INT NULL,
 is_mandatory BOOLEAN NULL, is_filter BOOLEAN NULL, allow_new_value BOOLEAN NULL, raw_json JSON NULL,
 UNIQUE(category_id, emag_parameter_id), FOREIGN KEY(category_id) REFERENCES pinfo_db.emag_categories(id)
);
CREATE TABLE pinfo_db.emag_parameter_values (
 id INT PRIMARY KEY, parameter_id INT NOT NULL, value_text TEXT NOT NULL, value_order INT NULL,
 INDEX idx_parameter_id(parameter_id), FOREIGN KEY(parameter_id) REFERENCES pinfo_db.emag_category_parameters(id)
);
INSERT INTO pinfo_db.emag_categories VALUES
 (10,1000,'Műszaki cikkek',NULL,1,0,0,NULL),
 (20,2000,'Laptopok',1000,1,1,1,NULL),
 (30,3000,'Hiányzó szülőjű kategória',10,1,0,0,NULL);
INSERT INTO pinfo_db.emag_category_parameters VALUES
 (70,20,9000,'Szín',2,1,1,1,0,NULL),
 (80,10,9000,'Másik kategória paramétere',1,1,0,0,1,NULL);
INSERT INTO pinfo_db.emag_parameter_values VALUES (100,70,'Fekete',1),(101,70,'Ezüst',2),(102,80,'Másik érték',1);
CREATE USER 'app'@'%' IDENTIFIED BY '{password}';
CREATE USER 'ref'@'%' IDENTIFIED BY '{password}';
GRANT ALL ON adatdusito_dev.* TO 'app'@'%';
GRANT SELECT ON pinfo_db.emag_categories TO 'ref'@'%';
GRANT SELECT ON pinfo_db.emag_category_parameters TO 'ref'@'%';
GRANT SELECT ON pinfo_db.emag_parameter_values TO 'ref'@'%';
