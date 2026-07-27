-- LocalLife Copilot MySQL initialization schema
-- Generated from the current SQLAlchemy ORM metadata.
-- Canonical production schema evolution is maintained in backend/migrations/versions/.
-- Target: MySQL 8.4, charset utf8mb4.

CREATE DATABASE IF NOT EXISTS `local_life`
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_0900_ai_ci;
USE `local_life`;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;
CREATE TABLE departments (
	id BINARY(16) NOT NULL, 
	parent_id BINARY(16), 
	code VARCHAR(64) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	path VARCHAR(1024) NOT NULL, 
	status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE', 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	version INTEGER UNSIGNED NOT NULL DEFAULT '1', 
	CONSTRAINT pk_departments PRIMARY KEY (id), 
	CONSTRAINT uq_departments_code UNIQUE (code), 
	CONSTRAINT ck_departments_status CHECK (status IN ('ACTIVE', 'DISABLED')), 
	CONSTRAINT fk_departments_parent FOREIGN KEY(parent_id) REFERENCES departments (id) ON DELETE SET NULL
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_departments_path ON departments (path(191));

CREATE INDEX ix_departments_parent ON departments (parent_id);

CREATE TABLE roles (
	id BINARY(16) NOT NULL, 
	code VARCHAR(64) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	is_system BOOL NOT NULL DEFAULT '0', 
	status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE', 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	version INTEGER UNSIGNED NOT NULL DEFAULT '1', 
	CONSTRAINT pk_roles PRIMARY KEY (id), 
	CONSTRAINT uq_roles_code UNIQUE (code), 
	CONSTRAINT ck_roles_status CHECK (status IN ('ACTIVE', 'DISABLED')), 
	CONSTRAINT ck_roles_is_system CHECK (is_system IN (0, 1))
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE permissions (
	id BINARY(16) NOT NULL, 
	code VARCHAR(128) NOT NULL, 
	resource_type VARCHAR(64) NOT NULL, 
	action VARCHAR(32) NOT NULL, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_permissions PRIMARY KEY (id), 
	CONSTRAINT uq_permissions_code UNIQUE (code), 
	CONSTRAINT uq_permissions_resource_action UNIQUE (resource_type, action)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE resource_grants (
	id BINARY(16) NOT NULL, 
	subject_type VARCHAR(16) NOT NULL, 
	subject_id BINARY(16) NOT NULL, 
	resource_type VARCHAR(32) NOT NULL, 
	resource_id BINARY(16) NOT NULL, 
	action VARCHAR(32) NOT NULL, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_resource_grants PRIMARY KEY (id), 
	CONSTRAINT uq_resource_grants_subject_resource_action UNIQUE (subject_type, subject_id, resource_type, resource_id, action), 
	CONSTRAINT ck_resource_grants_subject_type CHECK (subject_type IN ('USER', 'ROLE')), 
	CONSTRAINT ck_resource_grants_resource_type CHECK (resource_type IN ('KNOWLEDGE_BASE', 'MERCHANT', 'REGION'))
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_resource_grants_subject ON resource_grants (subject_type, subject_id);

CREATE INDEX ix_resource_grants_resource ON resource_grants (resource_type, resource_id);

CREATE TABLE conversations (
	id BINARY(16) NOT NULL, 
	owner_user_id BINARY(16) NOT NULL, 
	title VARCHAR(255), 
	status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE', 
	memory_backend VARCHAR(16) NOT NULL DEFAULT 'REDIS', 
	current_branch_message_id BINARY(16), 
	settings_json JSON NOT NULL, 
	deleted_at DATETIME(6), 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	version INTEGER UNSIGNED NOT NULL DEFAULT '1', 
	CONSTRAINT pk_conversations PRIMARY KEY (id), 
	CONSTRAINT ck_conversations_status CHECK (status IN ('ACTIVE', 'ARCHIVED', 'DELETED')), 
	CONSTRAINT ck_conversations_memory_backend CHECK (memory_backend IN ('REDIS', 'MYSQL'))
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_conversations_owner ON conversations (owner_user_id, status, updated_at);

CREATE TABLE messages (
	id BINARY(16) NOT NULL, 
	conversation_id BINARY(16) NOT NULL, 
	parent_message_id BINARY(16), 
	sequence_no INTEGER UNSIGNED NOT NULL, 
	request_id VARCHAR(64), 
	`role` VARCHAR(16) NOT NULL, 
	content MEDIUMTEXT NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	model_version_id BINARY(16), 
	prompt_tokens INTEGER UNSIGNED, 
	completion_tokens INTEGER UNSIGNED, 
	latency_ms INTEGER UNSIGNED, 
	error_code VARCHAR(64), 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_messages PRIMARY KEY (id), 
	CONSTRAINT uq_messages_sequence UNIQUE (conversation_id, sequence_no), 
	CONSTRAINT uq_messages_request UNIQUE (conversation_id, request_id), 
	CONSTRAINT ck_messages_role CHECK (role IN ('SYSTEM', 'USER', 'ASSISTANT', 'TOOL')), 
	CONSTRAINT ck_messages_status CHECK (status IN ('STREAMING', 'COMPLETED', 'FAILED', 'CANCELLED'))
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_messages_conversation_created ON messages (conversation_id, created_at);

CREATE TABLE datasets (
	id BINARY(16) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	task_type VARCHAR(64) NOT NULL, 
	dataset_hash CHAR(64) NOT NULL, 
	storage_uri VARCHAR(1000) NOT NULL, 
	filter_config_json JSON NOT NULL, 
	redaction_version VARCHAR(64) NOT NULL, 
	split_config_json JSON NOT NULL, 
	sample_count INTEGER UNSIGNED NOT NULL, 
	statistics_json JSON NOT NULL, 
	status VARCHAR(16) NOT NULL DEFAULT 'BUILDING', 
	quality_report_uri VARCHAR(1000), 
	quality_report_hash CHAR(64), 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_datasets PRIMARY KEY (id), 
	CONSTRAINT uq_datasets_hash UNIQUE (dataset_hash), 
	CONSTRAINT ck_datasets_status CHECK (status IN ('BUILDING', 'READY', 'REJECTED', 'ARCHIVED'))
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_datasets_status_created ON datasets (status, created_at);

CREATE TABLE prompt_definitions (
	id BINARY(16) NOT NULL, 
	code VARCHAR(64) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	scene VARCHAR(64) NOT NULL, 
	description VARCHAR(1000), 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_prompt_definitions PRIMARY KEY (id), 
	CONSTRAINT uq_prompt_definitions_code UNIQUE (code)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE model_definitions (
	id BINARY(16) NOT NULL, 
	code VARCHAR(64) NOT NULL, 
	name VARCHAR(128) NOT NULL, 
	task_type VARCHAR(64) NOT NULL, 
	provider VARCHAR(64) NOT NULL, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_model_definitions PRIMARY KEY (id), 
	CONSTRAINT uq_model_definitions_code UNIQUE (code)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE model_deployment_routes (
	id BINARY(16) NOT NULL, 
	scene VARCHAR(64) NOT NULL, 
	environment VARCHAR(32) NOT NULL, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_model_deployment_routes PRIMARY KEY (id), 
	CONSTRAINT uq_model_deployment_routes_key UNIQUE (scene, environment)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE review_analyses (
	id BINARY(16) NOT NULL, 
	merchant_id VARCHAR(128), 
	review_text TEXT NOT NULL, 
	sentiment VARCHAR(16) NOT NULL, 
	confidence FLOAT NOT NULL, 
	model_version VARCHAR(128) NOT NULL, 
	aspect_labels JSON NOT NULL DEFAULT '(''[]'')', 
	negative_reasons JSON NOT NULL DEFAULT '(''[]'')', 
	review_date DATETIME(6), 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	version INTEGER UNSIGNED NOT NULL DEFAULT '1', 
	CONSTRAINT pk_review_analyses PRIMARY KEY (id), 
	CONSTRAINT ck_review_analyses_sentiment CHECK (sentiment IN ('POSITIVE', 'NEUTRAL', 'NEGATIVE'))
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_review_analyses_review_date ON review_analyses (review_date);

CREATE INDEX ix_review_analyses_merchant_sentiment ON review_analyses (merchant_id, sentiment);

CREATE INDEX ix_review_analyses_sentiment_date ON review_analyses (sentiment, review_date);

CREATE TABLE async_tasks (
	id BINARY(16) NOT NULL, 
	task_type VARCHAR(64) NOT NULL, 
	resource_type VARCHAR(64) NOT NULL, 
	resource_id BINARY(16) NOT NULL, 
	target_version_no INTEGER UNSIGNED, 
	status VARCHAR(20) NOT NULL DEFAULT 'PENDING', 
	stage VARCHAR(20) NOT NULL DEFAULT 'QUEUED', 
	progress TINYINT UNSIGNED NOT NULL DEFAULT '0', 
	attempt_count INTEGER UNSIGNED NOT NULL DEFAULT '0', 
	max_attempts INTEGER UNSIGNED NOT NULL DEFAULT '3', 
	locked_by VARCHAR(128), 
	locked_until DATETIME(6), 
	heartbeat_at DATETIME(6), 
	error_code VARCHAR(64), 
	error_message TEXT, 
	result_json JSON, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	version INTEGER UNSIGNED NOT NULL DEFAULT '1', 
	CONSTRAINT pk_async_tasks PRIMARY KEY (id), 
	CONSTRAINT ck_async_tasks_status CHECK (status IN ('PENDING', 'RUNNING', 'CANCEL_REQUESTED', 'SUCCEEDED', 'FAILED', 'CANCELLED')), 
	CONSTRAINT ck_async_tasks_stage CHECK (stage IN ('QUEUED', 'LOADING', 'CLEANING', 'SPLITTING', 'PERSISTING', 'INDEXING', 'VERIFYING', 'DELETING')), 
	CONSTRAINT ck_async_tasks_progress CHECK (progress BETWEEN 0 AND 100), 
	CONSTRAINT ck_async_tasks_success_progress CHECK (status <> 'SUCCEEDED' OR progress = 100), 
	CONSTRAINT ck_async_tasks_max_attempts CHECK (max_attempts > 0), 
	CONSTRAINT ck_async_tasks_attempt_count CHECK (attempt_count <= max_attempts), 
	CONSTRAINT ck_async_tasks_target_version_no CHECK (target_version_no IS NULL OR target_version_no > 0)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_async_tasks_locked_until ON async_tasks (locked_until);

CREATE INDEX ix_async_tasks_status_type_created ON async_tasks (status, task_type, created_at);

CREATE INDEX ix_async_tasks_resource_target ON async_tasks (resource_type, resource_id, task_type, target_version_no, status);

CREATE TABLE outbox_events (
	event_id BINARY(16) NOT NULL, 
	aggregate_type VARCHAR(64) NOT NULL, 
	aggregate_id BINARY(16) NOT NULL, 
	event_type VARCHAR(128) NOT NULL, 
	event_version INTEGER UNSIGNED NOT NULL, 
	payload_json JSON NOT NULL, 
	occurred_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	published_at DATETIME(6), 
	attempt_count INTEGER UNSIGNED NOT NULL DEFAULT '0', 
	last_error TEXT, 
	locked_by VARCHAR(128), 
	locked_until DATETIME(6), 
	CONSTRAINT pk_outbox_events PRIMARY KEY (event_id), 
	CONSTRAINT ck_outbox_events_event_version CHECK (event_version > 0)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_outbox_unpublished ON outbox_events (published_at, occurred_at);

CREATE INDEX ix_outbox_locked_until ON outbox_events (locked_until);

CREATE TABLE users (
	id BINARY(16) NOT NULL, 
	department_id BINARY(16), 
	username VARCHAR(64) NOT NULL, 
	normalized_username VARCHAR(64) NOT NULL, 
	email VARCHAR(254), 
	normalized_email VARCHAR(254), 
	password_hash VARCHAR(255) NOT NULL, 
	display_name VARCHAR(128) NOT NULL, 
	status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE', 
	login_failed_count SMALLINT UNSIGNED NOT NULL DEFAULT '0', 
	locked_until DATETIME(6), 
	last_login_at DATETIME(6), 
	access_tokens_valid_after DATETIME(6), 
	deleted_at DATETIME(6), 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	version INTEGER UNSIGNED NOT NULL DEFAULT '1', 
	CONSTRAINT pk_users PRIMARY KEY (id), 
	CONSTRAINT uq_users_username UNIQUE (normalized_username), 
	CONSTRAINT uq_users_email UNIQUE (normalized_email), 
	CONSTRAINT ck_users_status CHECK (status IN ('ACTIVE', 'DISABLED', 'LOCKED')), 
	CONSTRAINT fk_users_department FOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE SET NULL
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_users_department_status ON users (department_id, status);

CREATE TABLE role_permissions (
	role_id BINARY(16) NOT NULL, 
	permission_id BINARY(16) NOT NULL, 
	CONSTRAINT pk_role_permissions PRIMARY KEY (role_id, permission_id), 
	CONSTRAINT fk_role_permissions_role FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE, 
	CONSTRAINT fk_role_permissions_permission FOREIGN KEY(permission_id) REFERENCES permissions (id) ON DELETE CASCADE
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE merchants (
	id BINARY(16) NOT NULL, 
	region_id BINARY(16), 
	category VARCHAR(128) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	normalized_name VARCHAR(200) NOT NULL, 
	address VARCHAR(500) NOT NULL, 
	longitude NUMERIC(10, 7) NOT NULL, 
	latitude NUMERIC(10, 7) NOT NULL, 
	avg_price_cent BIGINT UNSIGNED, 
	rating NUMERIC(3, 2) NOT NULL DEFAULT '0', 
	business_hours_json JSON, 
	business_status VARCHAR(16) NOT NULL DEFAULT 'UNKNOWN', 
	last_verified_at DATETIME(6), 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	version INTEGER UNSIGNED NOT NULL DEFAULT '1', 
	CONSTRAINT pk_merchants PRIMARY KEY (id), 
	CONSTRAINT ck_merchants_longitude CHECK (longitude BETWEEN -180 AND 180), 
	CONSTRAINT ck_merchants_latitude CHECK (latitude BETWEEN -90 AND 90), 
	CONSTRAINT ck_merchants_avg_price CHECK (avg_price_cent IS NULL OR avg_price_cent >= 0), 
	CONSTRAINT ck_merchants_rating CHECK (rating BETWEEN 0 AND 5), 
	CONSTRAINT ck_merchants_business_status CHECK (business_status IN ('OPEN', 'CLOSED', 'SUSPENDED', 'UNKNOWN')), 
	CONSTRAINT fk_merchants_region FOREIGN KEY(region_id) REFERENCES departments (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_merchants_region_status ON merchants (region_id, business_status);

CREATE INDEX ix_merchants_category_status ON merchants (category, business_status);

CREATE TABLE user_roles (
	user_id BINARY(16) NOT NULL, 
	role_id BINARY(16) NOT NULL, 
	granted_by BINARY(16), 
	granted_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_user_roles PRIMARY KEY (user_id, role_id), 
	CONSTRAINT fk_user_roles_user FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	CONSTRAINT fk_user_roles_role FOREIGN KEY(role_id) REFERENCES roles (id) ON DELETE CASCADE, 
	CONSTRAINT fk_user_roles_grantor FOREIGN KEY(granted_by) REFERENCES users (id) ON DELETE SET NULL
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE refresh_tokens (
	id BINARY(16) NOT NULL, 
	user_id BINARY(16) NOT NULL, 
	token_hash CHAR(64) NOT NULL, 
	expires_at DATETIME(6) NOT NULL, 
	revoked_at DATETIME(6), 
	replaced_by_id BINARY(16), 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	version INTEGER UNSIGNED NOT NULL DEFAULT '1', 
	CONSTRAINT pk_refresh_tokens PRIMARY KEY (id), 
	CONSTRAINT uq_refresh_tokens_hash UNIQUE (token_hash), 
	CONSTRAINT fk_refresh_tokens_user FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE, 
	CONSTRAINT fk_refresh_tokens_replacement FOREIGN KEY(replaced_by_id) REFERENCES refresh_tokens (id) ON DELETE SET NULL
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_refresh_tokens_user_revoked ON refresh_tokens (user_id, revoked_at);

CREATE TABLE feedback (
	id BINARY(16) NOT NULL, 
	user_id BINARY(16) NOT NULL, 
	message_id BINARY(16) NOT NULL, 
	rating SMALLINT NOT NULL, 
	correction TEXT, 
	reason_codes_json JSON, 
	pii_flagged TINYINT UNSIGNED NOT NULL DEFAULT '0', 
	review_status VARCHAR(20) NOT NULL DEFAULT 'PENDING_REVIEW', 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	version INTEGER UNSIGNED NOT NULL DEFAULT '1', 
	CONSTRAINT pk_feedback PRIMARY KEY (id), 
	CONSTRAINT uq_feedback_user_message UNIQUE (user_id, message_id), 
	CONSTRAINT ck_feedback_rating CHECK (rating IN (-1, 1)), 
	CONSTRAINT fk_feedback_user FOREIGN KEY(user_id) REFERENCES users (id), 
	CONSTRAINT fk_feedback_message FOREIGN KEY(message_id) REFERENCES messages (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_feedback_message_rating ON feedback (message_id, rating, created_at);

CREATE TABLE prompt_versions (
	id BINARY(16) NOT NULL, 
	prompt_definition_id BINARY(16) NOT NULL, 
	version_no INTEGER UNSIGNED NOT NULL, 
	content MEDIUMTEXT NOT NULL, 
	variables_json JSON NOT NULL, 
	status VARCHAR(16) NOT NULL DEFAULT 'DRAFT', 
	content_hash CHAR(64) NOT NULL, 
	created_by BINARY(16) NOT NULL, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	published_at DATETIME(6), 
	published_by BINARY(16), 
	publication_action VARCHAR(16), 
	publication_result VARCHAR(32), 
	CONSTRAINT pk_prompt_versions PRIMARY KEY (id), 
	CONSTRAINT uq_prompt_versions_definition_version UNIQUE (prompt_definition_id, version_no), 
	CONSTRAINT ck_prompt_versions_version_no CHECK (version_no > 0), 
	CONSTRAINT ck_prompt_versions_status CHECK (status IN ('DRAFT', 'PUBLISHED', 'ARCHIVED')), 
	CONSTRAINT ck_prompt_versions_publication_action CHECK (publication_action IS NULL OR publication_action IN ('PUBLISH', 'ROLLBACK')), 
	CONSTRAINT ck_prompt_versions_publication_result CHECK (publication_result IS NULL OR publication_result IN ('SUCCEEDED', 'FAILED')), 
	CONSTRAINT fk_prompt_versions_definition FOREIGN KEY(prompt_definition_id) REFERENCES prompt_definitions (id), 
	CONSTRAINT fk_prompt_versions_creator FOREIGN KEY(created_by) REFERENCES users (id), 
	CONSTRAINT fk_prompt_versions_publisher FOREIGN KEY(published_by) REFERENCES users (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_prompt_versions_definition_status ON prompt_versions (prompt_definition_id, status);

CREATE TABLE model_versions (
	id BINARY(16) NOT NULL, 
	model_definition_id BINARY(16) NOT NULL, 
	version VARCHAR(64) NOT NULL, 
	base_model_ref VARCHAR(500) NOT NULL, 
	adapter_uri VARCHAR(1000) NOT NULL, 
	artifact_sha256 CHAR(64) NOT NULL, 
	dimension INTEGER UNSIGNED, 
	labels_json JSON, 
	metrics_json JSON, 
	status VARCHAR(16) NOT NULL DEFAULT 'REGISTERED', 
	created_by BINARY(16) NOT NULL, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_model_versions PRIMARY KEY (id), 
	CONSTRAINT uq_model_versions_definition_version UNIQUE (model_definition_id, version), 
	CONSTRAINT ck_model_versions_status CHECK (status IN ('REGISTERED', 'EVALUATED', 'APPROVED', 'REJECTED', 'ARCHIVED')), 
	CONSTRAINT fk_model_versions_definition FOREIGN KEY(model_definition_id) REFERENCES model_definitions (id), 
	CONSTRAINT fk_model_versions_creator FOREIGN KEY(created_by) REFERENCES users (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_model_versions_definition_status ON model_versions (model_definition_id, status);

CREATE TABLE sensitive_word_rules (
	id BINARY(16) NOT NULL, 
	word VARCHAR(200) NOT NULL, 
	normalized_word VARCHAR(200) NOT NULL, 
	scope VARCHAR(16) NOT NULL, 
	match_type VARCHAR(16) NOT NULL, 
	severity VARCHAR(16) NOT NULL, 
	version_no INTEGER UNSIGNED NOT NULL, 
	enabled BOOL NOT NULL DEFAULT '1', 
	created_by BINARY(16) NOT NULL, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_sensitive_word_rules PRIMARY KEY (id), 
	CONSTRAINT uq_sensitive_rules_word_scope_version UNIQUE (normalized_word, scope, version_no), 
	CONSTRAINT ck_sensitive_word_rules_version_no CHECK (version_no > 0), 
	CONSTRAINT ck_sensitive_word_rules_scope CHECK (scope IN ('INPUT', 'OUTPUT', 'BOTH')), 
	CONSTRAINT ck_sensitive_word_rules_match_type CHECK (match_type IN ('CONTAINS', 'EXACT')), 
	CONSTRAINT ck_sensitive_word_rules_severity CHECK (severity IN ('LOW', 'MEDIUM', 'HIGH')), 
	CONSTRAINT fk_sensitive_rules_creator FOREIGN KEY(created_by) REFERENCES users (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_sensitive_rules_enabled_scope ON sensitive_word_rules (enabled, scope);

CREATE TABLE audit_logs (
	id BINARY(16) NOT NULL, 
	actor_id BINARY(16) NOT NULL, 
	action VARCHAR(64) NOT NULL, 
	resource_type VARCHAR(64) NOT NULL, 
	resource_id BINARY(16), 
	request_id VARCHAR(128) NOT NULL, 
	ip_address BLOB(16), 
	result VARCHAR(16) NOT NULL, 
	before_summary_json JSON, 
	after_summary_json JSON, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_audit_logs PRIMARY KEY (id), 
	CONSTRAINT ck_audit_logs_result CHECK (result IN ('SUCCEEDED', 'FAILED', 'BLOCKED')), 
	CONSTRAINT fk_audit_logs_actor FOREIGN KEY(actor_id) REFERENCES users (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_audit_logs_actor_created ON audit_logs (actor_id, created_at);

CREATE INDEX ix_audit_logs_resource_created ON audit_logs (resource_type, resource_id, created_at);

CREATE INDEX ix_audit_logs_result_created ON audit_logs (result, created_at);

CREATE TABLE knowledge_bases (
	id BINARY(16) NOT NULL, 
	tenant_id BINARY(16) NOT NULL, 
	department_id BINARY(16), 
	owner_id BINARY(16) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	normalized_name VARCHAR(200) NOT NULL, 
	description TEXT, 
	embedding_model_version_id BINARY(16) NOT NULL, 
	chunk_size SMALLINT UNSIGNED NOT NULL DEFAULT '500', 
	chunk_overlap SMALLINT UNSIGNED NOT NULL DEFAULT '80', 
	status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE', 
	deleted_at DATETIME(6), 
	active_flag BOOL GENERATED ALWAYS AS (CASE WHEN deleted_at IS NULL THEN 1 ELSE NULL END) STORED, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	version INTEGER UNSIGNED NOT NULL DEFAULT '1', 
	CONSTRAINT pk_knowledge_bases PRIMARY KEY (id), 
	CONSTRAINT uq_kb_tenant_name_active UNIQUE (tenant_id, normalized_name, active_flag), 
	CONSTRAINT ck_knowledge_bases_chunk_size CHECK (chunk_size BETWEEN 100 AND 4000), 
	CONSTRAINT ck_knowledge_bases_overlap CHECK (chunk_overlap < chunk_size), 
	CONSTRAINT ck_knowledge_bases_status CHECK (status IN ('ACTIVE', 'ARCHIVED', 'DELETED')), 
	CONSTRAINT fk_kb_tenant FOREIGN KEY(tenant_id) REFERENCES departments (id) ON DELETE RESTRICT, 
	CONSTRAINT fk_kb_department FOREIGN KEY(department_id) REFERENCES departments (id) ON DELETE SET NULL, 
	CONSTRAINT fk_kb_owner FOREIGN KEY(owner_id) REFERENCES users (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_kb_tenant_status ON knowledge_bases (tenant_id, status, created_at);

CREATE INDEX ix_kb_department_status ON knowledge_bases (department_id, status, created_at);

CREATE TABLE reviews (
	id BINARY(16) NOT NULL, 
	merchant_id BINARY(16) NOT NULL, 
	user_id BINARY(16), 
	author_ref VARCHAR(128), 
	content TEXT NOT NULL, 
	content_hash CHAR(64) NOT NULL, 
	rating NUMERIC(3, 2), 
	reviewed_at DATETIME(6) NOT NULL, 
	source_type VARCHAR(32) NOT NULL, 
	source_review_id VARCHAR(191), 
	status VARCHAR(16) NOT NULL DEFAULT 'PENDING', 
	tags_json JSON, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	version INTEGER UNSIGNED NOT NULL DEFAULT '1', 
	CONSTRAINT pk_reviews PRIMARY KEY (id), 
	CONSTRAINT uq_reviews_source UNIQUE (source_type, source_review_id), 
	CONSTRAINT ck_reviews_rating CHECK (rating IS NULL OR rating BETWEEN 0 AND 5), 
	CONSTRAINT ck_reviews_status CHECK (status IN ('PUBLISHED', 'PENDING', 'REJECTED', 'DELETED')), 
	CONSTRAINT fk_reviews_merchant FOREIGN KEY(merchant_id) REFERENCES merchants (id), 
	CONSTRAINT fk_reviews_user FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE SET NULL
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_reviews_merchant_status_date ON reviews (merchant_id, status, reviewed_at);

CREATE TABLE merchant_replies (
	id BINARY(16) NOT NULL, 
	review_id BINARY(16) NOT NULL COMMENT 'Logical reference to reviews.id or review_analyses.id', 
	merchant_id VARCHAR(128) NOT NULL COMMENT 'Matches ReviewAnalysis.merchant_id or merchants.id', 
	content TEXT NOT NULL, 
	tone VARCHAR(16) NOT NULL, 
	source VARCHAR(16) NOT NULL DEFAULT 'MANUAL', 
	status VARCHAR(16) NOT NULL DEFAULT 'PENDING', 
	created_by BINARY(16) NOT NULL, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_merchant_replies PRIMARY KEY (id), 
	CONSTRAINT ck_merchant_replies_source CHECK (source IN ('SUGGESTION', 'MANUAL')), 
	CONSTRAINT ck_merchant_replies_status CHECK (status IN ('PENDING', 'PUBLISHED', 'REJECTED')), 
	CONSTRAINT fk_merchant_replies_creator FOREIGN KEY(created_by) REFERENCES users (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_merchant_replies_status ON merchant_replies (status);

CREATE INDEX ix_merchant_replies_review ON merchant_replies (review_id);

CREATE INDEX ix_merchant_replies_merchant ON merchant_replies (merchant_id);

CREATE TABLE fine_tuning_jobs (
	id BINARY(16) NOT NULL, 
	dataset_id BINARY(16) NOT NULL, 
	async_task_id BINARY(16) NOT NULL, 
	task_type VARCHAR(64) NOT NULL, 
	base_model_ref VARCHAR(500) NOT NULL, 
	method VARCHAR(16) NOT NULL, 
	hyperparameters_json JSON NOT NULL, 
	hyperparameter_hash CHAR(64) NOT NULL, 
	seed INTEGER NOT NULL, 
	status VARCHAR(16) NOT NULL DEFAULT 'PENDING', 
	metrics_json JSON, 
	evaluation_json JSON, 
	log_uri VARCHAR(1000), 
	artifact_uri VARCHAR(1000), 
	artifact_sha256 CHAR(64), 
	created_by BINARY(16) NOT NULL, 
	completed_at DATETIME(6), 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_fine_tuning_jobs PRIMARY KEY (id), 
	CONSTRAINT uq_fine_tuning_job_spec UNIQUE (dataset_id, base_model_ref, hyperparameter_hash), 
	CONSTRAINT ck_fine_tuning_jobs_status CHECK (status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED', 'CANCELLED')), 
	CONSTRAINT fk_fine_tuning_jobs_dataset FOREIGN KEY(dataset_id) REFERENCES datasets (id), 
	CONSTRAINT uq_fine_tuning_jobs_async_task_id UNIQUE (async_task_id), 
	CONSTRAINT fk_fine_tuning_jobs_task FOREIGN KEY(async_task_id) REFERENCES async_tasks (id), 
	CONSTRAINT fk_fine_tuning_jobs_creator FOREIGN KEY(created_by) REFERENCES users (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_fine_tuning_jobs_status_created ON fine_tuning_jobs (status, created_at);

CREATE TABLE feedback_audits (
	id BINARY(16) NOT NULL, 
	feedback_id BINARY(16) NOT NULL, 
	version_no INTEGER UNSIGNED NOT NULL, 
	rating SMALLINT NOT NULL, 
	correction_snapshot TEXT, 
	reason_codes_snapshot JSON, 
	changed_by BINARY(16) NOT NULL, 
	changed_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_feedback_audits PRIMARY KEY (id), 
	CONSTRAINT fk_feedback_audits_feedback FOREIGN KEY(feedback_id) REFERENCES feedback (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_feedback_audits_feedback_version ON feedback_audits (feedback_id, version_no);

CREATE TABLE dataset_items (
	id BINARY(16) NOT NULL, 
	dataset_id BINARY(16) NOT NULL, 
	feedback_id BINARY(16), 
	conversation_id BINARY(16), 
	message_id BINARY(16), 
	user_id BINARY(16), 
	model_version_id BINARY(16), 
	split VARCHAR(12) NOT NULL, 
	content_json JSON NOT NULL, 
	content_hash CHAR(64) NOT NULL, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_dataset_items PRIMARY KEY (id), 
	CONSTRAINT ck_dataset_items_split CHECK (split IN ('train', 'validation', 'test')), 
	CONSTRAINT fk_dataset_items_dataset FOREIGN KEY(dataset_id) REFERENCES datasets (id), 
	CONSTRAINT fk_dataset_items_feedback FOREIGN KEY(feedback_id) REFERENCES feedback (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_dataset_items_feedback ON dataset_items (feedback_id);

CREATE INDEX ix_dataset_items_dataset_split ON dataset_items (dataset_id, split);

CREATE TABLE model_deployments (
	id BINARY(16) NOT NULL, 
	scene VARCHAR(64) NOT NULL, 
	environment VARCHAR(32) NOT NULL, 
	model_version_id BINARY(16) NOT NULL, 
	traffic_percent INTEGER UNSIGNED NOT NULL, 
	action VARCHAR(16) NOT NULL, 
	status VARCHAR(16) NOT NULL, 
	result VARCHAR(32) NOT NULL, 
	deployed_by BINARY(16) NOT NULL, 
	reason VARCHAR(1000) NOT NULL, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_model_deployments PRIMARY KEY (id), 
	CONSTRAINT ck_model_deployments_traffic_percent CHECK (traffic_percent BETWEEN 1 AND 100), 
	CONSTRAINT ck_model_deployments_action CHECK (action IN ('CANARY', 'FULL', 'ROLLBACK')), 
	CONSTRAINT ck_model_deployments_status CHECK (status IN ('ACTIVE', 'CANARY', 'SUPERSEDED', 'ROLLED_BACK')), 
	CONSTRAINT ck_model_deployments_result CHECK (result IN ('SUCCEEDED', 'FAILED')), 
	CONSTRAINT fk_model_deployments_version FOREIGN KEY(model_version_id) REFERENCES model_versions (id), 
	CONSTRAINT fk_model_deployments_actor FOREIGN KEY(deployed_by) REFERENCES users (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_model_deployments_route_status ON model_deployments (scene, environment, status);

CREATE TABLE documents (
	id BINARY(16) NOT NULL, 
	knowledge_base_id BINARY(16) NOT NULL, 
	source_type VARCHAR(32) NOT NULL, 
	source_key VARCHAR(500) NOT NULL, 
	display_name VARCHAR(255) NOT NULL, 
	mime_type VARCHAR(128), 
	status VARCHAR(16) NOT NULL DEFAULT 'UPLOADED', 
	current_version_no INTEGER UNSIGNED NOT NULL DEFAULT '0', 
	last_error_code VARCHAR(64), 
	deleted_at DATETIME(6), 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	version INTEGER UNSIGNED NOT NULL DEFAULT '1', 
	CONSTRAINT pk_documents PRIMARY KEY (id), 
	CONSTRAINT uq_documents_source UNIQUE (knowledge_base_id, source_type, source_key), 
	CONSTRAINT ck_documents_status CHECK (status IN ('UPLOADED', 'PARSING', 'INDEXING', 'READY', 'FAILED', 'ARCHIVED', 'DELETED')), 
	CONSTRAINT fk_documents_kb FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_documents_kb_status ON documents (knowledge_base_id, status, created_at);

CREATE TABLE data_sources (
	id BINARY(16) NOT NULL, 
	knowledge_base_id BINARY(16) NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	source_type VARCHAR(16) NOT NULL, 
	config_json JSON NOT NULL, 
	status VARCHAR(16) NOT NULL DEFAULT 'ACTIVE', 
	created_by BINARY(16) NOT NULL, 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	version INTEGER UNSIGNED NOT NULL DEFAULT '1', 
	CONSTRAINT pk_data_sources PRIMARY KEY (id), 
	CONSTRAINT uq_data_sources_kb_name UNIQUE (knowledge_base_id, name), 
	CONSTRAINT ck_data_sources_source_type CHECK (source_type IN ('CSV', 'FILE', 'WEB', 'API')), 
	CONSTRAINT ck_data_sources_status CHECK (status IN ('ACTIVE', 'DISABLED', 'DELETED')), 
	CONSTRAINT fk_data_sources_kb FOREIGN KEY(knowledge_base_id) REFERENCES knowledge_bases (id), 
	CONSTRAINT fk_data_sources_creator FOREIGN KEY(created_by) REFERENCES users (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_data_sources_kb_status ON data_sources (knowledge_base_id, status);

CREATE TABLE document_versions (
	id BINARY(16) NOT NULL, 
	document_id BINARY(16) NOT NULL, 
	version_no INTEGER UNSIGNED NOT NULL, 
	file_uri VARCHAR(1000) NOT NULL, 
	file_sha256 CHAR(64) NOT NULL, 
	file_size BIGINT UNSIGNED NOT NULL, 
	parser_name VARCHAR(64) NOT NULL, 
	parser_version VARCHAR(64) NOT NULL, 
	cleaning_config_json JSON NOT NULL, 
	splitter_config_json JSON NOT NULL, 
	is_current BOOL NOT NULL DEFAULT '1', 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_document_versions PRIMARY KEY (id), 
	CONSTRAINT uq_doc_version UNIQUE (document_id, version_no), 
	CONSTRAINT ck_document_versions_version_no CHECK (version_no > 0), 
	CONSTRAINT ck_document_versions_file_size CHECK (file_size > 0), 
	CONSTRAINT ck_document_versions_is_current CHECK (is_current IN (0, 1)), 
	CONSTRAINT fk_doc_versions_document FOREIGN KEY(document_id) REFERENCES documents (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE TABLE chunks (
	id BINARY(16) NOT NULL, 
	document_version_id BINARY(16) NOT NULL, 
	chunk_no INTEGER UNSIGNED NOT NULL, 
	content MEDIUMTEXT NOT NULL, 
	content_hash CHAR(64) NOT NULL, 
	token_count INTEGER UNSIGNED NOT NULL, 
	page_number INTEGER UNSIGNED, 
	metadata_json JSON NOT NULL, 
	embedding_model_version_id BINARY(16) NOT NULL, 
	opensearch_document_id VARCHAR(191) NOT NULL, 
	index_status VARCHAR(16) NOT NULL DEFAULT 'PENDING', 
	indexed_at DATETIME(6), 
	created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6), 
	CONSTRAINT pk_chunks PRIMARY KEY (id), 
	CONSTRAINT uq_chunks_no UNIQUE (document_version_id, chunk_no), 
	CONSTRAINT uq_chunks_os_id UNIQUE (opensearch_document_id), 
	CONSTRAINT ck_chunks_token_count CHECK (token_count > 0), 
	CONSTRAINT ck_chunks_index_status CHECK (index_status IN ('PENDING', 'INDEXED', 'FAILED', 'DELETED')), 
	CONSTRAINT fk_chunks_version FOREIGN KEY(document_version_id) REFERENCES document_versions (id)
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

CREATE INDEX ix_chunks_index_status ON chunks (index_status, updated_at);

CREATE TABLE message_sources (
	message_id BINARY(16) NOT NULL, 
	chunk_id BINARY(16) NOT NULL, 
	rank_no SMALLINT UNSIGNED NOT NULL, 
	score NUMERIC(8, 7), 
	raw_score DOUBLE, 
	source_location_snapshot VARCHAR(1000) NOT NULL, 
	content_snapshot TEXT NOT NULL, 
	CONSTRAINT pk_message_sources PRIMARY KEY (message_id, chunk_id), 
	CONSTRAINT uq_message_sources_rank UNIQUE (message_id, rank_no), 
	CONSTRAINT ck_message_sources_rank_no CHECK (rank_no > 0), 
	CONSTRAINT fk_message_sources_message FOREIGN KEY(message_id) REFERENCES messages (id) ON DELETE CASCADE, 
	CONSTRAINT fk_message_sources_chunk FOREIGN KEY(chunk_id) REFERENCES chunks (id) ON DELETE CASCADE
)CHARSET=utf8mb4 ENGINE=InnoDB COLLATE utf8mb4_0900_ai_ci;

ALTER TABLE messages ADD CONSTRAINT fk_messages_parent FOREIGN KEY(parent_message_id) REFERENCES messages (id);

ALTER TABLE messages ADD CONSTRAINT fk_messages_conversation FOREIGN KEY(conversation_id) REFERENCES conversations (id);

ALTER TABLE conversations ADD CONSTRAINT fk_conversations_owner FOREIGN KEY(owner_user_id) REFERENCES users (id);

ALTER TABLE conversations ADD CONSTRAINT fk_conversations_branch FOREIGN KEY(current_branch_message_id) REFERENCES messages (id) ON DELETE SET NULL;
SET FOREIGN_KEY_CHECKS = 1;
