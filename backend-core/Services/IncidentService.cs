using Microsoft.AspNetCore.Http;
using Microsoft.EntityFrameworkCore;
using TechDocIntelligence.Backend.Clients;
using TechDocIntelligence.Backend.Data;
using TechDocIntelligence.Backend.Models.DTOs;

namespace TechDocIntelligence.Backend.Services;

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
        var ingestContent = IncidentMapping.BuildIngestContent(entity, request.SubsystemTags);
        var metadata = IncidentMapping.BuildMetadata(entity, request.SubsystemTags);

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

        return IncidentMapping.Map(entity, chunksIndexed);
    }

    public async Task<IncidentReportDto?> GetByIdAsync(
        Guid id,
        CancellationToken cancellationToken = default)
    {
        var entity = await _dbContext.Incidents
            .AsNoTracking()
            .FirstOrDefaultAsync(incident => incident.Id == id, cancellationToken);

        return entity is null ? null : IncidentMapping.Map(entity, chunksIndexed: 0);
    }

    public async Task<IReadOnlyList<IncidentReportDto>> ListAsync(
        CancellationToken cancellationToken = default)
    {
        var entities = await _dbContext.Incidents
            .AsNoTracking()
            .OrderByDescending(incident => incident.CreatedAt)
            .Take(500)
            .ToListAsync(cancellationToken);

        return entities.Select(entity => IncidentMapping.Map(entity, chunksIndexed: 0)).ToList();
    }

    public async Task<AskIncidentResponseDto> AnalyzeIncidentAsync(
        AskIncidentQueryDto request,
        CancellationToken cancellationToken = default)
    {
        var analysis = await _aiServiceClient.QueryIncidentsAsync(request, cancellationToken);
        var filteredCitations = await IncidentMapping.ApplyMinSeverityFilterAsync(
            _dbContext,
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

    public async Task<DocumentDeleteResponseDto> DeleteAsync(
        Guid id,
        CancellationToken cancellationToken = default)
    {
        DocumentDeleteResponseDto result;
        try
        {
            result = await _aiServiceClient.DeleteDocumentAsync(id, cancellationToken);
        }
        catch (AiServiceException ex) when (ex.StatusCode == System.Net.HttpStatusCode.NotFound)
        {
            result = new DocumentDeleteResponseDto(
                Success: false,
                DocumentId: id.ToString("D"),
                Status: "not_found",
                VectorsDeleted: 0,
                PostgresDeleted: false,
                CacheEntriesInvalidated: 0,
                Message: ex.Message);
        }

        var local = await _dbContext.Incidents.FirstOrDefaultAsync(
            incident => incident.Id == id,
            cancellationToken);
        if (local is not null)
        {
            _dbContext.Incidents.Remove(local);
            await _dbContext.SaveChangesAsync(cancellationToken);
            if (!result.PostgresDeleted)
            {
                result = result with
                {
                    PostgresDeleted = true,
                    Success = true,
                    Status = "deleted",
                    Message = result.Message + " Local Postgres row removed by backend.",
                };
            }
        }

        _logger.LogInformation(
            "Deleted incident {IncidentId}: vectors={Vectors}, postgres={Postgres}, cache={Cache}, status={Status}",
            id,
            result.VectorsDeleted,
            result.PostgresDeleted,
            result.CacheEntriesInvalidated,
            result.Status);

        return result;
    }
}
