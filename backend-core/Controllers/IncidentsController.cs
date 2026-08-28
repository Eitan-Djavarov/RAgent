using System.Net.Http;
using Microsoft.AspNetCore.Mvc;
using TechDocIntelligence.Backend.Clients;
using TechDocIntelligence.Backend.Models.DTOs;
using TechDocIntelligence.Backend.Services;

namespace TechDocIntelligence.Backend.Controllers;

[ApiController]
[Route("api/[controller]")]
[Produces("application/json")]
public sealed class IncidentsController : ControllerBase
{
    private readonly IIncidentService _incidentService;
    private readonly IAiServiceClient _aiServiceClient;
    private readonly ILogger<IncidentsController> _logger;

    public IncidentsController(
        IIncidentService incidentService,
        IAiServiceClient aiServiceClient,
        ILogger<IncidentsController> logger)
    {
        _incidentService = incidentService;
        _aiServiceClient = aiServiceClient;
        _logger = logger;
    }

    /// <summary>
    /// Creates an incident report, persists it to PostgreSQL, and triggers AI ingestion.
    /// </summary>
    [HttpPost]
    [ProducesResponseType(typeof(IncidentReportDto), StatusCodes.Status201Created)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    public async Task<ActionResult<IncidentReportDto>> CreateAsync(
        [FromBody] CreateIncidentRequestDto request,
        CancellationToken cancellationToken)
    {
        if (!ModelState.IsValid)
        {
            return ValidationProblem(ModelState);
        }

        var created = await _incidentService.CreateAsync(request, cancellationToken);
        return CreatedAtAction(nameof(GetById), new { id = created.Id }, created);
    }

    /// <summary>
    /// Lists persisted incident reports (most recent first).
    /// </summary>
    [HttpGet]
    [ProducesResponseType(typeof(IReadOnlyList<IncidentReportDto>), StatusCodes.Status200OK)]
    public async Task<ActionResult<IReadOnlyList<IncidentReportDto>>> ListAsync(
        CancellationToken cancellationToken)
    {
        var incidents = await _incidentService.ListAsync(cancellationToken);
        return Ok(incidents);
    }

    /// <summary>
    /// Runs enriched hybrid RAG analysis with optional system/severity filters.
    /// </summary>
    [HttpPost("ask")]
    [HttpPost("analyze")]
    [ProducesResponseType(typeof(AskIncidentResponseDto), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status502BadGateway)]
    [ProducesResponseType(StatusCodes.Status504GatewayTimeout)]
    [ProducesResponseType(StatusCodes.Status429TooManyRequests)]
    public async Task<ActionResult<AskIncidentResponseDto>> AskAsync(
        [FromBody] AskIncidentQueryDto request,
        CancellationToken cancellationToken)
    {
        if (!ModelState.IsValid)
        {
            return ValidationProblem(ModelState);
        }

        try
        {
            var analysis = await _incidentService.AnalyzeIncidentAsync(request, cancellationToken);
            return Ok(analysis);
        }
        catch (AiServiceException ex)
        {
            _logger.LogError(ex, "AI analysis failed");
            var problem = AiErrorMapper.ToProblemDetails(ex, HttpContext.TraceIdentifier, "AI service error");
            AiErrorMapper.ApplyRateLimitHeaders(Response, ex, problem);
            return StatusCode(problem.Status, problem);
        }
    }

    /// <summary>
    /// Proxies an SSE token stream from the AI ask/stream endpoint.
    /// </summary>
    [HttpPost("ask/stream")]
    [Produces("text/event-stream")]
    [ProducesResponseType(StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status502BadGateway)]
    [ProducesResponseType(StatusCodes.Status429TooManyRequests)]
    public async Task AskStreamAsync(
        [FromBody] AskIncidentQueryDto request,
        CancellationToken cancellationToken)
    {
        if (!ModelState.IsValid)
        {
            Response.StatusCode = StatusCodes.Status400BadRequest;
            Response.ContentType = "application/json";
            await Response.WriteAsJsonAsync(
                new ProblemDetailsDto(
                    "https://tools.ietf.org/html/rfc7807",
                    "Validation failed",
                    StatusCodes.Status400BadRequest,
                    "Invalid ask/stream request.",
                    HttpContext.TraceIdentifier),
                cancellationToken);
            return;
        }

        HttpResponseMessage? upstream = null;
        try
        {
            upstream = await _aiServiceClient.StreamQueryIncidentsAsync(request, cancellationToken);
            Response.StatusCode = StatusCodes.Status200OK;
            Response.ContentType = "text/event-stream";
            Response.Headers.CacheControl = "no-cache, no-transform";
            Response.Headers.Append("X-Accel-Buffering", "no");
            Response.Headers.Append("Connection", "keep-alive");

            await using var upstreamStream = await upstream.Content.ReadAsStreamAsync(cancellationToken);
            await upstreamStream.CopyToAsync(Response.Body, cancellationToken);
            await Response.Body.FlushAsync(cancellationToken);
        }
        catch (AiServiceException ex)
        {
            _logger.LogError(ex, "AI ask/stream proxy failed");
            if (!Response.HasStarted)
            {
                var problem = AiErrorMapper.ToProblemDetails(ex, HttpContext.TraceIdentifier, "AI stream error");
                Response.StatusCode = problem.Status;
                Response.ContentType = "application/json";
                AiErrorMapper.ApplyRateLimitHeaders(Response, ex, problem);
                await Response.WriteAsJsonAsync(problem, cancellationToken);
            }
        }
        finally
        {
            upstream?.Dispose();
        }
    }

    /// <summary>
    /// Proxies a multipart document upload to the AI ingestion pipeline.
    /// </summary>
    [HttpPost("upload")]
    [RequestSizeLimit(52_428_800)]
    [Consumes("multipart/form-data")]
    [ProducesResponseType(typeof(FileIngestResponseDto), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status400BadRequest)]
    [ProducesResponseType(StatusCodes.Status502BadGateway)]
    [ProducesResponseType(StatusCodes.Status504GatewayTimeout)]
    public async Task<ActionResult<FileIngestResponseDto>> UploadAsync(
        IFormFile file,
        [FromForm] string system,
        [FromForm] string severity,
        [FromForm] string? subsystemTags = null,
        [FromForm] string? title = null,
        CancellationToken cancellationToken = default)
    {
        if (file is null || file.Length == 0)
        {
            return BadRequest("A non-empty file is required.");
        }

        if (string.IsNullOrWhiteSpace(system) || string.IsNullOrWhiteSpace(severity))
        {
            return BadRequest("system and severity are required.");
        }

        try
        {
            var result = await _incidentService.UploadDocumentAsync(
                file,
                title,
                system.Trim(),
                severity.Trim(),
                subsystemTags,
                cancellationToken);
            return Ok(result);
        }
        catch (ArgumentException ex)
        {
            return BadRequest(ex.Message);
        }
        catch (AiServiceException ex)
        {
            _logger.LogError(ex, "AI file ingestion proxy failed");
            var statusCode = ex.StatusCode switch
            {
                System.Net.HttpStatusCode.RequestTimeout => StatusCodes.Status504GatewayTimeout,
                System.Net.HttpStatusCode.BadRequest => StatusCodes.Status400BadRequest,
                _ => StatusCodes.Status502BadGateway,
            };

            return StatusCode(
                statusCode,
                new ProblemDetailsDto(
                    $"https://httpstatuses.com/{statusCode}",
                    "AI upload error",
                    statusCode,
                    ex.Message,
                    HttpContext.TraceIdentifier));
        }
    }

    /// <summary>
    /// Fetches a persisted incident report by id.
    /// </summary>
    [HttpGet("{id:guid}")]
    [ProducesResponseType(typeof(IncidentReportDto), StatusCodes.Status200OK)]
    [ProducesResponseType(StatusCodes.Status404NotFound)]
    public async Task<ActionResult<IncidentReportDto>> GetById(
        Guid id,
        CancellationToken cancellationToken)
    {
        var incident = await _incidentService.GetByIdAsync(id, cancellationToken);
        if (incident is null)
        {
            return NotFound();
        }

        return Ok(incident);
    }
}
