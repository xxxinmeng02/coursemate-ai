# CourseMate AI Roadmap

## Phase 0: Product Definition

- Target user: university students reviewing course materials.
- Main pain point: course information is scattered across slides, specs, past exams, and notes.
- Main promise: answer questions and create study materials with clear citations.

## Phase 1: MVP

Build the smallest useful version:

- Upload PDF/TXT files.
- Parse text and preserve page metadata.
- Chunk documents and store embeddings.
- Ask questions against uploaded materials.
- Return answers with source citations.

Definition of done:

- A user can upload at least three files for one course.
- A user can ask five course-related questions.
- Each answer includes at least one citation.
- The demo can be run locally from documented steps.

## Phase 2: Study Generation

Add outputs that feel useful to students:

- Summaries by lecture.
- Revision notes.
- Multiple-choice questions.
- True/false questions.
- Exportable study sets.

Definition of done:

- Generated questions cite the source chunk.
- The user can regenerate or save study materials.
- The UI separates Q&A from study-set generation.

## Phase 3: Evaluation

Make the project credible for job applications:

- Build a small evaluation set from real course materials.
- Track retrieval hit rate.
- Track citation support quality.
- Add regression tests for parsing and retrieval.

Definition of done:

- Evaluation script can be run with one command.
- Results are documented in the README.
- At least one chart or table shows model/retriever quality.

## Phase 4: Portfolio Polish

- Add screenshots.
- Add architecture diagram.
- Add demo video link.
- Add deployment instructions.
- Add a short technical write-up.

