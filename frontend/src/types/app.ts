export type AppSession = {
  user: {
    id: number
    twitch_user_id?: string
    login: string
    display_name: string
    profile_image_url?: string
  }
  active_channel: {
    id: number
    login: string
    display_name: string
    profile_image_url?: string
    role: "owner" | "moderator"
    is_active: boolean
  }
  channels: Array<{
    id: number
    login: string
    display_name: string
    profile_image_url?: string
    role: "owner" | "moderator"
    is_active: boolean
  }>
  is_admin: boolean
  routes: {
    dashboard: string
    quiz: string
    stats: string
    settings: string
    timers: string
    admin: string
    commands: string
    giveaways: string
    autobet: string
  }
}

export type DashboardPayload = {
  title: string
  user: AppSession["user"]
  status: {
    chat_connected: boolean
    bot_is_moderator: boolean
    chat_status_text: string
    bot_status_online_label: string
    bot_status_offline_label: string
  }
  overlay_url: string
  bot_login: string
  bot_token_configured: boolean
  can_manage_bot_account: boolean
  is_admin: boolean
  settings: {
    answer_cooldown_seconds: number
    command_access: string
    overlay_theme: string
    turbo_mode: boolean
    quiz_passive_mode: boolean
    quiet_mode: boolean
    chat_questions_enabled: boolean
    chat_outcomes_enabled: boolean
  }
  quiz: {
    is_active: boolean
    paused: boolean
    passive_mode: boolean
    passive_waiting_for_live: boolean
    passive_result_seconds_left: number
    auto_rounds_stopped: boolean
    next_round_in: number
    seconds_left: number
    last_no_winner: boolean
    category: string
    hint: string
    masked_answer: string
    top_players: Array<{
      username: string
      points: number
      wins: number
    }>
    season: {
      id: number
      title: string
      status: string
      starts_at: string
      ends_at: string
      closed_at: string
      seconds_left: number
      top_players: Array<{
        username: string
        points: number
        wins: number
      }>
    } | null
    season_history: Array<{
      id: number
      title: string
      status: string
      starts_at: string
      ends_at: string
      closed_at: string
      top_players: Array<{
        username: string
        points: number
        wins: number
      }>
    }>
  }
  configs: Array<{
    id: number
    name: string
    file_name: string
    kind_label: string
    is_active: boolean
    is_standard: boolean
  }>
  action_logs: Array<{
    id: number
    action: string
    title: string
    detail: string
    actor_login: string
    actor_display_name: string
    created_at: string
    created_at_formatted: string
  }>
  active_preview: Array<{
    category?: string
    hint?: string
    answer?: string
  }>
  using_standard_config: boolean
  limits: {
    custom_configs_max: number
    custom_limit_reached: boolean
  }
  options: {
    command_access: Array<{
      value: string
      label: string
    }>
    overlay_theme: Array<{
      value: string
      label: string
      description: string
    }>
  }
}

export type MutationResult = {
  ok: boolean
  saved?: boolean
  warning?: string
  error?: string
  message?: string
  timers?: TimerItem[]
}

export type TimerItem = {
  id: number
  name: string
  enabled: boolean
  offline_enabled: boolean
  online_enabled: boolean
  offline_interval_minutes: number
  online_interval_minutes: number
  minimum_lines: number
  commands: string[]
  messages: string[]
  line_count: number
  created_at: string
}

export type TimersPayload = {
  title: string
  user: AppSession["user"]
  timers: TimerItem[]
  commands: Array<{
    name: string
    label: string
    response_text: string
  }>
}

export type AutoBetSettings = {
  user_id: number
  dota2_enabled: boolean
  dota2_custom_questions_enabled: boolean
  dota2_custom_kills_enabled: boolean
  dota2_custom_deaths_enabled: boolean
  dota2_custom_assists_enabled: boolean
  dota2_custom_duration_enabled: boolean
  cs2_enabled: boolean
  cs2_custom_questions_enabled: boolean
  cs2_custom_win_enabled: boolean
  cs2_custom_kills_enabled: boolean
  cs2_custom_deaths_enabled: boolean
  cs2_custom_assists_enabled: boolean
  prediction_window_seconds: number
  prediction_title_template: string
  gsi_token: string
  gsi_last_seen_at: number
  gsi_match_id: string
  gsi_game_state: string
  gsi_game_time: number
  gsi_hero_id: number
  gsi_hero_name: string
  gsi_kills: number
  gsi_deaths: number
  gsi_assists: number
  active_prediction_id: string
  active_game_key: string
  active_game_name: string
  active_prediction_title: string
  win_outcome_id: string
  loss_outcome_id: string
  win_outcome_title: string
  loss_outcome_title: string
  last_opened_stream_signature: string
  last_error: string
  last_error_at: number
  created_at: string
  updated_at: string
}

export type GameGsiStatus = {
  connected: boolean
  last_seen_at: number
  seconds_since_last_seen: number
  match_id: string
  phase: string
  is_live: boolean
  is_finished: boolean
  kills: number
  deaths: number
  assists: number
}

export type AutoBetPayload = {
  title: string
  user: AppSession["user"]
  settings: AutoBetSettings
  games: Array<{
    key: "dota2" | "cs2"
    label: string
    enabled: boolean
  }>
  active_prediction: {
    id: string
    game_key: string
    game_name: string
    title: string
    win_outcome_id: string
    loss_outcome_id: string
    win_outcome_title: string
    loss_outcome_title: string
    status: string
    created_at: string
    locks_at: string
    seconds_remaining: number
    total_users: number
    total_channel_points: number
    sync_error: string
    outcomes: Array<{
      id: string
      title: string
      users: number
      channel_points: number
      color: string
      top_predictor_login: string
      top_predictor_display_name: string
      top_predictor_points: number
    }>
  } | null
  history: Array<{
    id: number
    prediction_id: string
    game_key: string
    game_name: string
    title: string
    outcome_title: string
    status: string
    total_channel_points: number
    total_users: number
    created_at: string
  }>
  gsi: {
    token: string
    endpoint_url: string
    cs2_endpoint_url: string
    install_script_url: string
    short_install_url: string
    install_command: string
    pairing_install_command: string
    config_filename: string
    config_text: string
    cs2_config_filename: string
    cs2_config_text: string
    connected: boolean
    last_seen_at: number
    seconds_since_last_seen: number
    match_id: string
    game_state: string
    game_time: number
    hero_id: number
    hero_name: string
    kills: number
    deaths: number
    assists: number
    dota2: GameGsiStatus
    cs2: GameGsiStatus
  }
  obs_overlay_url: string
  limits: {
    prediction_window_min_seconds: number
    prediction_window_max_seconds: number
  }
  oauth_reauth_url: string
  detection_note: string
}

export type CommandItem = {
  id: number | null
  name: string
  title: string
  description: string
  response_text: string
  enabled: boolean
  cooldown_seconds: number
  allowed_roles: string[]
  aliases: string[]
  keywords: string[]
  is_builtin: boolean
  can_delete: boolean
}

export type CommandsPayload = {
  title: string
  user: AppSession["user"]
  commands: CommandItem[]
}

export type CommandsMutationResult = MutationResult & {
  commands?: CommandItem[]
}

export type GiveawayParticipant = {
  user_id: string
  login: string
  display_name: string
  entry_count: number
  message_count: number
  is_follower: boolean
  is_vip: boolean
  is_subscriber: boolean
  multiplier: number
}

export type GiveawayState = {
  running: boolean
  giveaway_type: "active" | "keyword" | "points"
  keyword: string
  chat_announcements: boolean
  points_reward_title: string
  points_reward_cost: number
  points_allow_multiple_entries: boolean
  points_reward_id: string
  points_reward_ready: boolean
  points_subscription_ready: boolean
  multipliers: {
    default: number
    follower: number
    vip: number
    subscriber: number
  }
  participants: GiveawayParticipant[]
  winner: GiveawayParticipant | null
  wheel_eliminated_logins: string[]
  wheel_last_result: GiveawayParticipant | null
  wheel_last_mode: "normal" | "elimination"
  wheel_last_source: string
  winner_messages: Array<{
    display_name: string
    login: string
    text: string
    created_at: string
  }>
  recent_messages: Array<{
    display_name: string
    login: string
    text: string
    created_at: string
  }>
}

export type GiveawaysPayload = {
  title: string
  user: AppSession["user"]
  state: GiveawayState
}

export type StatsPayload = {
  title: string
  user: AppSession["user"]
  stats_cards: Array<{
    value: number
    label: string
    description: string
  }>
  stats_highlights: Array<{
    label: string
    value: number
  }>
  recent_channels: Array<{
    display_name: string
    login: string
    connected_at: string
    updated_at: string
    overlay_url: string
    is_live: boolean
    chat_connected: boolean
    turbo_mode: boolean
    quiet_mode: boolean
    uses_custom_config: boolean
    custom_command_count: number
    enabled_custom_command_count: number
    timer_count: number
    enabled_timer_count: number
    action_log_count: number
    command_alias_count: number
    command_keyword_count: number
    stream_title: string
    stream_category: string
    viewer_count: number
  }>
  stats_updated_at: string
  service_metrics: {
    updated_at: string
    uptime_seconds: number
    uptime_label: string
    health: {
      status: "healthy" | "warning" | "error"
      label: string
    }
    overview_cards: Array<{
      label: string
      value: number | string
      description: string
      tone: "default" | "success" | "warning" | "error"
    }>
    pipelines: Array<{
      label: string
      status: "healthy" | "warning" | "error"
      status_label: string
      detail: string
    }>
    operations: Array<{
      label: string
      avg_ms: number
      last_ms: number
      max_ms: number
      count: number
    }>
    counters: Array<{
      label: string
      value: number
    }>
    recent_errors: Array<{
      key: string
      message: string
      age_label: string
    }>
  }
}

export type SettingsPayload = {
  title: string
  user: AppSession["user"]
  admin_users: Array<{
    id: number
    login: string
    display_name: string
    created_at_formatted: string
    updated_at_formatted: string
  }>
  admin_candidates: Array<{
    id: number
    login: string
    display_name: string
    created_at_formatted: string
    updated_at_formatted: string
  }>
  standard_question_presets: Array<{
      preset_id: string
      file_name: string
      name: string
      question_count: number
      is_builtin: boolean
      linked_user_count: number
    }>
  global_settings: {
    autobet_require_stream_online: boolean
    quiz_passive_debug_allow_offline: boolean
    custom_market_ranges: {
      dota2: {
        kills: { min: number; max: number }
        deaths: { min: number; max: number }
        assists: { min: number; max: number }
        duration: { min: number; max: number }
      }
      cs2: {
        kills: { min: number; max: number }
        deaths: { min: number; max: number }
        assists: { min: number; max: number }
      }
    }
  }
  autobet_debug_channels: Array<{
    id: number
    login: string
    display_name: string
    dota2_enabled: boolean
    cs2_enabled: boolean
    active_prediction_id: string
    active_game_key: string
    gsi: {
      dota2: {
        connected: boolean
        seconds_since_last_seen: number
        last_seen_label: string
        match_id: string
        game_state: string
        game_time: number
        subject_label: string
        score_line: string
        mode_label: string
        extra_label: string
        opening_allowed: boolean
        block_reason: string
        last_error: string
      }
      cs2: {
        connected: boolean
        seconds_since_last_seen: number
        last_seen_label: string
        match_id: string
        game_state: string
        game_time: number
        subject_label: string
        score_line: string
        mode_label: string
        extra_label: string
        opening_allowed: boolean
        block_reason: string
        last_error: string
      }
    }
  }>
  settings_updated_at: string
  current_user_is_admin: boolean
  service_metrics: StatsPayload["service_metrics"]
}
