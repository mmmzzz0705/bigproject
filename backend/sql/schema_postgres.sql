-- =========================================================
-- 政务智能问答与办事引导系统 · PostgreSQL 数据库初始化脚本
-- 与《系统设计》第四章"数据库详细设计"保持一致
--
-- 执行：psql -h 127.0.0.1 -p 5433 -U postgres -f sql/schema_postgres.sql
--       （先 CREATE DATABASE gov_qa; 再 \c gov_qa 后执行本文件）
-- =========================================================

-- 1. 会话表
CREATE TABLE IF NOT EXISTS session (
  session_id  VARCHAR(64)  NOT NULL,
  create_time TIMESTAMP    NOT NULL,
  PRIMARY KEY (session_id)
);
COMMENT ON TABLE  session            IS '会话表';
COMMENT ON COLUMN session.session_id IS '会话唯一标识';
COMMENT ON COLUMN session.create_time IS '会话创建时间';

-- 2. 对话历史表
CREATE TABLE IF NOT EXISTS chat_history (
  id          SERIAL       NOT NULL,
  session_id  VARCHAR(64)  NOT NULL,
  question    TEXT         NOT NULL,
  answer      TEXT         NOT NULL,
  create_time TIMESTAMP    NOT NULL,
  PRIMARY KEY (id),
  CONSTRAINT fk_chat_session FOREIGN KEY (session_id)
    REFERENCES session (session_id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chat_history_session ON chat_history (session_id);
CREATE INDEX IF NOT EXISTS idx_chat_history_time    ON chat_history (create_time);
COMMENT ON TABLE  chat_history            IS '对话历史表';
COMMENT ON COLUMN chat_history.session_id IS '关联 session 会话';
COMMENT ON COLUMN chat_history.question   IS '用户提问内容';
COMMENT ON COLUMN chat_history.answer     IS 'AI 返回回答内容';
COMMENT ON COLUMN chat_history.create_time IS '消息记录时间';

-- 3. 文档元数据表
CREATE TABLE IF NOT EXISTS doc_meta (
  doc_id      VARCHAR(64)  NOT NULL,
  doc_name    VARCHAR(255) NOT NULL,
  source      VARCHAR(255) NOT NULL DEFAULT '',
  upload_time TIMESTAMP    NOT NULL,
  PRIMARY KEY (doc_id)
);
COMMENT ON TABLE  doc_meta            IS '文档元数据表';
COMMENT ON COLUMN doc_meta.doc_id     IS '文档唯一编号';
COMMENT ON COLUMN doc_meta.doc_name   IS '文档名称';
COMMENT ON COLUMN doc_meta.source     IS '文档来源';
COMMENT ON COLUMN doc_meta.upload_time IS '文档入库时间';
