export interface Source {
  video_id: string;
  title: string;
  channel: string;
  url: string;
  timestamp_url: string;
  start_timestamp: number;
  is_web: boolean;
}

export interface Message {
  role: "user" | "assistant";
  content: string;
  sources?: Source[];
}

export interface Conversation {
  id: string;
  title: string;
  messages: Message[];
  updatedAt: number;
}
