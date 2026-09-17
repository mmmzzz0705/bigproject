-- =========================================================
-- 政务智能问答与办事引导系统 · MySQL 数据库初始化脚本
-- 与《系统设计》第四章"数据库详细设计"保持一致
-- =========================================================

CREATE DATABASE IF NOT EXISTS gov_qa
  DEFAULT CHARACTER SET utf8mb4
  DEFAULT COLLATE utf8mb4_general_ci;

USE gov_qa;

-- 1. 会话表
CREATE TABLE IF NOT EXISTS `session` (
  `session_id`  VARCHAR(64)  NOT NULL COMMENT '会话唯一标识',
  `create_time` DATETIME     NOT NULL COMMENT '会话创建时间',
  PRIMARY KEY (`session_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='会话表';

-- 2. 对话历史表
CREATE TABLE IF NOT EXISTS `chat_history` (
  `id`          INT          NOT NULL AUTO_INCREMENT COMMENT '自增主键',
  `session_id`  VARCHAR(64)  NOT NULL COMMENT '关联 session 会话',
  `question`    TEXT         NOT NULL COMMENT '用户提问内容',
  `answer`      TEXT         NOT NULL COMMENT 'AI 返回回答内容',
  `create_time` DATETIME     NOT NULL COMMENT '消息记录时间',
  PRIMARY KEY (`id`),
  KEY `idx_session_id` (`session_id`),
  CONSTRAINT `fk_chat_session` FOREIGN KEY (`session_id`)
    REFERENCES `session` (`session_id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话历史表';

-- 3. 文档元数据表
CREATE TABLE IF NOT EXISTS `doc_meta` (
  `doc_id`      VARCHAR(64)  NOT NULL COMMENT '文档唯一编号',
  `doc_name`    VARCHAR(255) NOT NULL COMMENT '文档名称',
  `source`      VARCHAR(255) NOT NULL DEFAULT '' COMMENT '文档来源',
  `upload_time` DATETIME     NOT NULL COMMENT '文档入库时间',
  PRIMARY KEY (`doc_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='文档元数据表';

-- 可选扩展（便于按会话检索最近记录）
-- ALTER TABLE `chat_history` ADD INDEX `idx_create_time` (`create_time`);
