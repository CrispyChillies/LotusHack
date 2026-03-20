CREATE TABLE "users" (
  "id" uuid PRIMARY KEY,
  "full_name" varchar,
  "email" varchar UNIQUE,
  "role" varchar,
  "persona" text,
  "voice_sample_s3_url" varchar,
  "voice_status" varchar,
  "created_at" timestamp
);

CREATE TABLE "families" (
  "id" uuid PRIMARY KEY,
  "patient_id" uuid,
  "name" varchar,
  "created_at" timestamp
);

CREATE TABLE "user_relations" (
  "id" uuid PRIMARY KEY,
  "subject_user_id" uuid,
  "object_user_id" uuid,
  "relation_name" varchar,
  "family_id" uuid
);

CREATE TABLE "media" (
  "id" uuid PRIMARY KEY,
  "family_id" uuid,
  "uploaded_by" uuid,
  "s3_url" varchar,
  "media_type" varchar,
  "captured_at" timestamp,
  "ai_summary" text,
  "uploaded_at" timestamp
);

CREATE TABLE "memories" (
  "id" uuid PRIMARY KEY,
  "family_id" uuid,
  "title" varchar,
  "ai_generated_story" text,
  "date_of_memory" timestamp
);

CREATE TABLE "memory_media" (
  "memory_id" uuid,
  "media_id" uuid
);

CREATE TABLE "reminders" (
  "id" uuid PRIMARY KEY,
  "patient_id" uuid,
  "related_user_id" uuid,
  "title" varchar,
  "reminder_context" text,
  "trigger_time" timestamp,
  "is_active" boolean,
  "generated_audio_s3_url" varchar
);

CREATE TABLE "memory_stories_audio" (
  "id" uuid PRIMARY KEY,
  "memory_id" uuid,
  "speaker_user_id" uuid,
  "audio_s3_url" varchar,
  "duration" integer,
  "status" varchar,
  "created_at" timestamp
);

ALTER TABLE "families" ADD FOREIGN KEY ("patient_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "user_relations" ADD FOREIGN KEY ("subject_user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "user_relations" ADD FOREIGN KEY ("object_user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "user_relations" ADD FOREIGN KEY ("family_id") REFERENCES "families" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "media" ADD FOREIGN KEY ("family_id") REFERENCES "families" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "media" ADD FOREIGN KEY ("uploaded_by") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "memories" ADD FOREIGN KEY ("family_id") REFERENCES "families" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "memory_media" ADD FOREIGN KEY ("memory_id") REFERENCES "memories" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "memory_media" ADD FOREIGN KEY ("media_id") REFERENCES "media" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "reminders" ADD FOREIGN KEY ("patient_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "reminders" ADD FOREIGN KEY ("related_user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "memory_stories_audio" ADD FOREIGN KEY ("memory_id") REFERENCES "memories" ("id") DEFERRABLE INITIALLY IMMEDIATE;

ALTER TABLE "memory_stories_audio" ADD FOREIGN KEY ("speaker_user_id") REFERENCES "users" ("id") DEFERRABLE INITIALLY IMMEDIATE;
