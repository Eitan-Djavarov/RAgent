using System.ComponentModel.DataAnnotations;

namespace TechDocIntelligence.Backend.Models.DTOs;

public sealed class CreateIncidentRequestDto
{
    [Required]
    [MaxLength(512)]
    public required string Title { get; init; }

    [Required]
    [MinLength(1)]
    public required string Description { get; init; }

    [Required]
    [MaxLength(256)]
    public required string SystemName { get; init; }

    [Required]
    [EnumDataType(typeof(IncidentSeverity))]
    public IncidentSeverity Severity { get; init; }

    public IReadOnlyList<string>? SubsystemTags { get; init; }
}
