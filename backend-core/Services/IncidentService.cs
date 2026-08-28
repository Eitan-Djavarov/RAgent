using Microsoft.AspNetCore.Http;
using Microsoft.EntityFrameworkCore;
using TechDocIntelligence.Backend.Clients;
using TechDocIntelligence.Backend.Data;
using TechDocIntelligence.Backend.Models.DTOs;

namespace TechDocIntelligence.Backend.Services;

public interface IIncidentService
{
    Task<IncidentReportDto> CreateAsync(
        CreateIncidentRequestDto request,
        CancellationToken cancellationToken = default);

    Task<IncidentReportDto?> GetByIdAsync(Guid id, CancellationToken cancellationToken = default);

    Task<IReadOnlyList<IncidentReportDto>> ListAsync(CancellationToken cancellationToken = default);

    Task<AskIncidentResponseDto> AnalyzeIncidentAsync(
        AskIncidentQueryDto request,
        CancellationToken cancellationToken = default);

    Task<FileIngestResponseDto> UploadDocumentAsync(
        IFormFile file,
        string? title,
        string system,
        string severity,
        string? subsystemTags,
        CancellationToken cancellationToken = default);
}

public sealed class IncidentService : IIncidentService
{
    private readonly AppDbContext _dbContext;
    private readonly IAiServiceClient _aiServiceClient;
    private readonly ILogger<IncidentService> _logger;

    public IncidentService(
        AppDbContext dbContext,
        IAiServiceClient aiServiceClient,
        ILogger<IncidentService> logger)
    {
        _dbContext = dbContext;
        _aiServiceClient = aiServiceClient;
        _logger = logger;
    }

    public async Task<IncidentReportDto> CreateAsync(
        CreateIncidentRequestDto request,
        CancellationToken cancellationToken = default)
    {
        var entity = new IncidentEntity
        {
            Id = Guid.NewGuid(),
            Title = request.Title.Trim(),
            Description = request.Description.Trim(),
            SystemName = request.SystemName.Trim(),
            Severity = request.Severity,
            CreatedAt = DateTimeOffset.UtcNow,
        };

        _dbContext.Incidents.Add(entity);
        await _dbContext.SaveChangesAsync(cancellationToken);

        var chunksIndexed = 0;
        var ingestContent = BuildIngestContent(entity, request.SubsystemTags);
        var metadata = BuildMetadata(entity, request.SubsystemTags);

        try
        {
            var ingestResult = await _aiServiceClient.IngestAsync(
                new AiIngestRequestDto(
                    entity.Id.ToString("D"),
                    entity.Title,
                    ingestContent,
                    metadata),
                cancellationToken);

            chunksIndexed = ingestResult.ChunksCount;
            entity.IngestionMessage = ingestResult.Message;

            if (ingestResult.Success)
            {
                entity.IndexedAt = DateTimeOffset.UtcNow;
            }
            else
            {
                _logger.LogWarning(
                    "AI ingestion reported failure for incident {IncidentId}: {Message}",
                    entity.Id,
                    ingestResult.Message);
            }

            await _dbContext.SaveChangesAsync(cancellationToken);
        }
        catch (Exception ex) when (ex is AiServiceException or HttpRequestException or TaskCanceledException)
        {
            _logger.LogError(
                ex,
                "Failed to ingest incident {IncidentId} into AI service; incident was persisted",
                entity.Id);
            entity.IngestionMessage = ex.Message;
            await _dbContext.SaveChangesAsync(cancellationToken);
        }

        return Map(entity, chunksIndexed);
    }

    public async Task<IncidentReportDto?> GetByIdAsync(
        Guid id,
        CancellationToken cancellationToken = default)
    {
        var entity = await _dbContext.Incidents
            .AsNoTracking()
            .FirstOrDefaultAsync(incident => incident.Id == id, cancellationToken);

        return entity is null ? null : Map(entity, chunksIndexed: 0);
    }

    public async Task<IReadOnlyList<IncidentReportDto>> ListAsync(
        CancellationToken cancellationToken = default)
    {
        var entities = await _dbContext.Incidents
            .AsNoTracking()
            .OrderByDescending(incident => incident.CreatedAt)
            .Take(500)
            .ToListAsync(cancellationToken);

        return entities.Select(entity => Map(entity, chunksIndexed: 0)).ToList();
    }

    public async Task<AskIncidentResponseDto> AnalyzeIncidentAsync(
        AskIncidentQueryDto request,
        CancellationToken cancellationToken = default)
    {
        var analysis = await _aiServiceClient.QueryIncidentsAsync(request, cancellationToken);
        var filteredCitations = await ApplyMinSeverityFilterAsync(
            analysis.Citations,
            request.MinSeverity,
            cancellationToken);

        if (ReferenceEquals(filteredCitations, analysis.Citations))
        {
            return analysis;
        }

        return analysis with { Citations = filteredCitations };
    }

    public async Task<FileIngestResponseDto> UploadDocumentAsync(
        IFormFile file,
        string? title,
        string system,
        string severity,
        string? subsystemTags,
        CancellationToken cancellationToken = default)
    {
        if (file.Length <= 0)
        {
            throw new ArgumentException("Uploaded file is empty.", nameof(file));
        }

        await using var stream = file.OpenReadStream();
        var result = await _aiServiceClient.IngestFileAsync(
            stream,
            file.FileName,
            file.ContentType,
            title,
            system,
            severity,
            subsystemTags,
            cancellationToken);

        _logger.LogInformation(
            "Uploaded document {DocumentId} indexed with {ChunkCount} chunks (status={Status})",
            result.DocumentId,
            result.ChunkCount,
            result.Status);

        return result;
    }

    private async Task<IReadOnlyList<IncidentCitationDto>> ApplyMinSeverityFilterAsync(
        IReadOnlyList<IncidentCitationDto> citations,
        string? minSeverity,
        CancellationToken cancellationToken)
    {
        if (!AiResponseMapper.TryParseSeverity(minSeverity, out var minimum)
            || citations.Count == 0)
        {
            return citations;
        }

        var documentIds = citations
            .Select(citation => Guid.TryParse(citation.DocumentId, out var id) ? id : Guid.Empty)
            .Where(id => id != Guid.Empty)
            .Distinct()
            .ToList();

        if (documentIds.Count == 0)
        {
            return citations;
        }

        var severityById = await _dbContext.Incidents
            .AsNoTracking()
            .Where(incident => documentIds.Contains(incident.Id))
            .Select(incident => new { incident.Id, incident.Severity })
            .ToDictionaryAsync(row => row.Id, row => row.Severity, cancellationToken);

        return citations
            .Where(citation =>
            {
                if (!Guid.TryParse(citation.DocumentId, out var id))
                {
                    return true;
                }

                if (!severityById.TryGetValue(id, out var severity))
                {
                    return true;
                }

                return severity >= minimum;
            })
            .ToList();
    }

    private static Dictionary<string, string?> BuildMetadata(
        IncidentEntity entity,
        IReadOnlyList<string>? subsystemTags)
    {
        var metadata = new Dictionary<string, string?>
        {
            ["type"] = "incident",
            ["systemName"] = entity.SystemName,
            ["severity"] = entity.Severity.ToString(),
        };

        if (subsystemTags is { Count: > 0 })
        {
            metadata["subsystemTags"] = string.Join(",", subsystemTags.Select(tag => tag.Trim())
                .Where(tag => !string.IsNullOrWhiteSpace(tag)));
        }

        return metadata;
    }

    private static string BuildIngestContent(
        IncidentEntity entity,
        IReadOnlyList<string>? subsystemTags)
    {
        var tags = subsystemTags is { Count: > 0 }
            ? string.Join(", ", subsystemTags)
            : "n/a";

        return $"""
            Incident Report
            Title: {entity.Title}
            System: {entity.SystemName}
            Severity: {entity.Severity}
            Subsystem Tags: {tags}
            Description:
            {entity.Description}
            """;
    }

    private static IncidentReportDto Map(IncidentEntity entity, int chunksIndexed) =>
        new(
            entity.Id,
            entity.Title,
            entity.Description,
            entity.SystemName,
            entity.Severity,
            entity.CreatedAt,
            entity.IndexedAt,
            chunksIndexed,
            entity.IngestionMessage);
}
