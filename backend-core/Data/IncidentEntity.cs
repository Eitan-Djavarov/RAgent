using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;
using TechDocIntelligence.Backend.Models.DTOs;

namespace TechDocIntelligence.Backend.Data;

[Table("incidents")]
public sealed class IncidentEntity
{
    [Key]
    [Column("id")]
    public Guid Id { get; set; }

    [Required]
    [MaxLength(512)]
    [Column("title")]
    public required string Title { get; set; }

    [Required]
    [Column("description")]
    public required string Description { get; set; }

    [Required]
    [MaxLength(256)]
    [Column("system_name")]
    public required string SystemName { get; set; }

    [Column("severity")]
    public IncidentSeverity Severity { get; set; }

    [Column("created_at")]
    public DateTimeOffset CreatedAt { get; set; }

    [Column("indexed_at")]
    public DateTimeOffset? IndexedAt { get; set; }

    [Column("ingestion_message")]
    [MaxLength(1024)]
    public string? IngestionMessage { get; set; }
}
