/** Playground 文件信息（比全局类型宽松，file_type 为 string） */
export interface FileInfo {
  file_id: string;
  filename: string;
  file_size: number;
  file_type?: string;
  is_scanned?: boolean;
}

/** Playground 实体（type 为 string 以兼容自定义类型） */
export interface Entity {
  id: string;
  text: string;
  type: string;
  start: number;
  end: number;
  selected: boolean;
  source: 'regex' | 'llm' | 'manual' | 'has';
  coref_id?: string | null;
}

/** Playground 边界框（含视觉检测元数据） */
export interface BoundingBox {
  id: string;
  x: number;
  y: number;
  width: number;
  height: number;
  page?: number;
  type: string;
  text?: string;
  selected: boolean;
  confidence?: number;
  source?: 'ocr_has' | 'has_image' | 'manual';
}

export interface EntityTypeConfig {
  id: string;
  name: string;
  color: string;
  description?: string;
  regex_pattern?: string | null;
  use_llm?: boolean;
  enabled?: boolean;
}

export interface VisionTypeConfig {
  id: string;
  name: string;
  color: string;
  description?: string;
  enabled?: boolean;
}

export interface PipelineConfig {
  mode: 'ocr_has' | 'has_image';
  name: string;
  description: string;
  enabled: boolean;
  types: VisionTypeConfig[];
}

export type Stage = 'upload' | 'preview' | 'result';
