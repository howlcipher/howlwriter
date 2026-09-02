/**
 * TypeScript definitions for HowlWriter Local Web Application.
 */

export type WritingMode = 'general' | 'academic' | 'casual' | 'professional' | 'technical' | 'documentation' | 'email' | 'article' | 'custom' | 'linkedin';

export const WRITING_MODES: WritingMode[] = [
  'general', 'article', 'linkedin', 'academic', 'technical', 'professional',
  'documentation', 'email', 'casual', 'custom',
];

export interface DocumentData {
  path?: string | null;
  title: string;
  content: string;
  word_count: number;
  char_count: number;
  line_count: number;
  mode: WritingMode;
}

export interface RuleMatch {
  rule_code: string;
  message: string;
  matched_text: string;
  category?: string | null;
  severity: string;
  paragraph_index?: number | null;
  sentence_index?: number | null;
  snippet?: string | null;
  replacement?: string | null;
  suggestion?: string | null;
}

export interface LintResponse {
  matches: RuleMatch[];
  banned_words_count: number;
  ai_style_warnings_count: number;
  total_count: number;
}

export interface RedPenFinding {
  finding: string;
  reason: string;
  recommendation: string;
  category: string;
  severity: string;
  location?: string | null;
  paragraph_index?: number | null;
  snippet?: string | null;
}

export interface RedPenResponse {
  findings: RedPenFinding[];
  total_count: number;
}

export interface ChangeRecord {
  description: string;
  category: string;
  reason?: string | null;
  location?: string | null;
}

export interface HumanizeResponse {
  original_text: string;
  transformed_text: string;
  changes: ChangeRecord[];
  rationale: string;
  warnings: string[];
  provider?: string | null;
  model?: string | null;
  duration_seconds: number;
  independence_status: string;
  lint_before: RuleMatch[];
  lint_after: RuleMatch[];
  lint_before_count: number;
  lint_after_count: number;
  banned_words_count: number;
  ai_style_warnings_count: number;
  meaning_preservation_status: string;
  semantic_meaning_status?: string | null;
  mode?: string | null;
  change_count: number;
  run_id: string;
  status: string;
}

export interface HowlPipelineResponse {
  original_text: string;
  final_text: string;
  lint_matches: RuleMatch[];
  red_pen_findings: RedPenFinding[];
  meaning_preservation: string;
  semantic_meaning_status?: string | null;
  status: string;
  run_id: string;
  report: Record<string, any>;
}

export interface SourceRequirements {
  minimum_sources: number;
  prefer_primary_sources: boolean;
  scholarly_or_authoritative: boolean;
  allowed_types: string[];
}

export interface AssignmentSpec {
  title: string;
  topic: string;
  type: string;
  target_words: number;
  word_tolerance_percent: number;
  citation_style: string;
  source_requirements: SourceRequirements;
  requirements: string[];
  outline: string[];
  voice_profile?: string | null;
  metadata: Record<string, any>;
}

export interface ValidateSpecResponse {
  valid: boolean;
  errors: string[];
  spec: AssignmentSpec;
  yaml_preview: string;
}

export interface ReviewReason {
  category: 'RESEARCH_SUFFICIENCY' | 'SOURCE_CLAIM_SUPPORT' | 'SEMANTIC_REVIEW' | 'WORD_COUNT' | 'OUTLINE' | 'CITATIONS' | 'OTHER';
  severity: 'info' | 'warning' | 'critical';
  title: string;
  explanation: string;
}

export interface Source {
  id: string;
  title: string;
  authors: string[];
  publication_date?: string | null;
  url?: string | null;
  doi?: string | null;
  publisher?: string | null;
  source_type?: string | null;
  retrieved_text?: string | null;
  claims_count: number;
  in_text_citations_count: number;
  relevance: 'DIRECT' | 'SUPPORTING' | 'TANGENTIAL' | 'IRRELEVANT' | string;
  evidence_origin: 'FULL_TEXT' | 'ABSTRACT' | 'METADATA_ONLY' | 'OTHER' | string;
  relevance_notes?: string | null;
  raw_metadata?: Record<string, any>;
  metadata: Record<string, any>;
}

export interface Evidence {
  id: string;
  source_id: string;
  source_title: string;
  source_url?: string | null;
  source_doi?: string | null;
  excerpt: string;
  origin_type: 'FULL_TEXT' | 'ABSTRACT' | 'METADATA_ONLY' | 'OTHER' | string;
  page_or_section?: string | null;
  confidence: number;
}

export interface Claim {
  id: string;
  claim_text: string;
  verdict: string; // SUPPORTED, PARTIALLY_SUPPORTED, UNSUPPORTED, CONTRADICTED
  evidence_ids: string[];
  source_ids: string[];
  evidence: Evidence[];
  reasoning?: string | null;
  paragraph_index?: number | null;
  in_text_citations: string[];
}

export interface AcademicResult {
  paper_text: string;
  title: string;
  topic: string;
  target_words: number;
  min_words: number;
  max_words: number;
  actual_body_words: number;
  word_count_status: string;
  outline_status: string;
  required_outline_topics: number;
  present_outline_topics: number;
  sources_retrieved: number;
  sources_used: number;
  sources_required: number;
  sources_sufficiency_status: 'SUFFICIENT' | 'DEFICIENT' | string;
  supported_claims: number;
  partially_supported_claims: number;
  unsupported_claims: number;
  contradicted_claims: number;
  citation_style: string;
  in_text_citations: number;
  reference_entries: number;
  citation_warnings: number;
  writer_provider?: string | null;
  researcher_provider?: string | null;
  humanizer_provider?: string | null;
  meaning_reviewer_provider?: string | null;
  meaning_reviewer_verdict?: string | null;
  meaning_reviewer_explanation?: string | null;
  reviewer_independence?: string | null;
  reviewer_independence_reason?: string | null;
  banned_words: number;
  ai_style_warnings: number;
  meaning_preservation: string;
  semantic_meaning_status?: string | null;
  status: string;
  run_id: string;
  sources: Source[];
  claims: Claim[];
  references_text: string;
  warnings: string[];
  review_reasons: ReviewReason[];
}

export interface Stage {
  id: string;
  label: string;
  status: 'PENDING' | 'RUNNING' | 'DONE' | 'FAILED';
  started_at?: number | null;
  completed_at?: number | null;
  data: Record<string, any>;
}

export interface JobResponse {
  job_id: string;
  run_id: string;
  job_type: string;
  status: 'QUEUED' | 'RUNNING' | 'COMPLETED' | 'FAILED';
  created_at: number;
  updated_at: number;
  elapsed_seconds: number;
  current_stage_id?: string | null;
  stages: Stage[];
  error_message?: string | null;
  failure_category?: string | null;
  result?: AcademicResult | null;
}

export interface RunRecord {
  run_id: string;
  timestamp: string;
  command: string;
  writing_mode?: string | null;
  success: boolean;
  status: string;
  humanizer_provider?: string | null;
  meaning_reviewer_provider?: string | null;
  reviewer_independence?: string | null;
  lint_before_count?: number | null;
  lint_after_count?: number | null;
  banned_words?: number | null;
  ai_style_warnings?: number | null;
  meaning_preservation?: string | null;
  semantic_meaning_status?: string | null;
  humanizer_duration_seconds?: number | null;
  meaning_reviewer_duration_seconds?: number | null;
  total_duration_seconds?: number | null;
  input_path?: string | null;
  input_chars: number;
  input_sha256?: string | null;
  output_chars?: number | null;
  output_sha256?: string | null;
  failure_category?: string | null;
  error_message?: string | null;
  exit_code: number;
  howlplane_task_ids: string[];
  metadata: Record<string, any>;
}

export interface RoleBinding {
  role: string;
  role_label: string;
  domain: string;
  provider?: string | null;
  model?: string | null;
  is_configured: boolean;
  timeout_seconds: number;
  description: string;
}

export interface ProviderStatus {
  id: string;
  name: string;
  is_installed: boolean;
  command_path?: string | null;
  description: string;
}

export interface ProvidersResponse {
  bridge_available: boolean;
  role_bindings: RoleBinding[];
  available_providers: ProviderStatus[];
  reviewer_independence: string; // INDEPENDENT, SAME_PROVIDER, NOT_REVIEWED, UNAVAILABLE
  reviewer_independence_reason: string;
}

// --- Personal Voices ---
//
// Everything the UI receives about a voice is a summary. There is no field
// here that can hold a corpus passage, and source paths arrive only from the
// separate, explicitly-confirmed sources endpoint.

export interface VoiceTrait {
  name: string;
  value: string;
  confidence: number;
  confidence_band: 'HIGH' | 'MEDIUM' | 'LOW' | 'VERY_LOW' | 'UNKNOWN';
  supporting_documents: number;
  supporting_words: number;
  agreement: number;
  source: 'deterministic' | 'model' | 'user';
}

export interface VoiceContextBlock {
  name: string;
  document_count: number;
  word_count: number;
  confidence: number;
  sufficiency: string;
  traits: VoiceTrait[];
}

export interface VoiceCorpusSummary {
  documents_discovered: number;
  unique_canonical_files: number;
  candidate_prose_files: number;
  included_documents: number;
  holdout_documents: number;
  excluded_documents: number;
  held_for_review_documents: number;
  exact_duplicates: number;
  cross_format_duplicates: number;
  revision_groups: number;
  extraction_failures: number;
  scanned_or_unreadable: number;
  training_words: number;
  holdout_words: number;
  sufficiency: string;
  sufficiency_warnings: string[];
  words_by_context: Record<string, number>;
  documents_by_context: Record<string, number>;
  quality_classifications: Record<string, number>;
  exclusion_reasons: Record<string, number>;
}

export interface VoiceValidation {
  alignment: Record<string, string>;
  overall_confidence: string;
  holdout_documents: number;
  holdout_words: number;
  diversity_preservation: string;
  warnings: string[];
}

export interface VoiceOverrides {
  preserve: string[];
  avoid: string[];
  traits: Record<string, string>;
  notes: string;
}

export interface VoiceSummary {
  name: string;
  profile_type: 'personal_voice' | 'shared_style';
  built_at: string;
  included_documents: number;
  training_words: number;
  contexts: string[];
  overall_confidence: string;
  sufficiency: string;
}

export interface VoiceDetail {
  name: string;
  profile_type: 'personal_voice' | 'shared_style';
  built_at: string;
  version: number;
  traits: VoiceTrait[];
  contexts: VoiceContextBlock[];
  corpus: VoiceCorpusSummary;
  validation: VoiceValidation;
  overrides: VoiceOverrides;
  warnings: string[];
  distributions: Record<string, number>;
}
