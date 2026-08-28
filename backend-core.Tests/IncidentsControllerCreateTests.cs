using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Extensions.Logging.Abstractions;
using Moq;
using TechDocIntelligence.Backend.Clients;
using TechDocIntelligence.Backend.Controllers;
using TechDocIntelligence.Backend.Models.DTOs;
using TechDocIntelligence.Backend.Services;

namespace TechDocIntelligence.Backend.Tests;

public sealed class IncidentsControllerCreateTests
{
    [Fact]
    public async Task CreateAsync_ReturnsCreatedAtAction_PointingToGetById()
    {
        var incidentId = Guid.Parse("11111111-1111-1111-1111-111111111111");
        var created = new IncidentReportDto(
            incidentId,
            "UAV SATCOM link degradation under electronic warfare jamming",
            "Detailed description",
            "Tactical-UAV-V2",
            IncidentSeverity.Critical,
            DateTimeOffset.UtcNow,
            DateTimeOffset.UtcNow,
            ChunksIndexed: 3,
            IngestionMessage: "ok");

        var service = new Mock<IIncidentService>(MockBehavior.Strict);
        service
            .Setup(s => s.CreateAsync(It.IsAny<CreateIncidentRequestDto>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(created);

        var ai = new Mock<IAiServiceClient>(MockBehavior.Loose);
        var controller = new IncidentsController(
            service.Object,
            ai.Object,
            NullLogger<IncidentsController>.Instance)
        {
            ControllerContext = new ControllerContext
            {
                HttpContext = new DefaultHttpContext(),
            },
        };

        var result = await controller.CreateAsync(
            new CreateIncidentRequestDto
            {
                Title = created.Title,
                Description = created.Description,
                SystemName = created.SystemName,
                Severity = created.Severity,
            },
            CancellationToken.None);

        var createdResult = Assert.IsType<CreatedAtActionResult>(result.Result);
        Assert.Equal(nameof(IncidentsController.GetById), createdResult.ActionName);
        Assert.NotNull(createdResult.RouteValues);
        Assert.Equal(incidentId, createdResult.RouteValues["id"]);
        Assert.Same(created, createdResult.Value);
        service.VerifyAll();
    }
}
