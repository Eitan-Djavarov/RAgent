using System.ComponentModel.DataAnnotations;

namespace TechDocIntelligence.Backend.Models.DTOs;

public sealed class AskIncidentQueryDto
{
    [Required]
    [MinLength(1)]
    [MaxLength(4000)]
    public required string QueryText { get; init; }

    /// <summary>
    /// Optional exact system filter forwarded to AI metadata filtering (e.g. "Radar-APG").
    /// </summary>
    [MaxLength(256)]
    public string? SystemName { get; init; }

    /// <summary>
    /// Optional minimum severity gate (Low, Medium, High, Critical).
    /// Results below this severity are excluded after retrieval.
    /// </summary>
    [MaxLength(32)]
    public string? MinSeverity { get; init; }

    /// <summary>
    /// Number of re-ranked chunks to request from the AI service.
    /// </summary>
    [Range(1, 20)]
    public int TopK { get; init; } = 4;

    /// <summary>
    /// Optional conversational session id for multi-turn memory / query rewriting.
    /// </summary>
    [MaxLength(128)]
    public string? SessionId { get; init; }
}
