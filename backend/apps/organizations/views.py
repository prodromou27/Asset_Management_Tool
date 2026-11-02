from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import generics, status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts import catalog
from apps.accounts.permissions import ReadAnyWritePermission

from . import scope, services
from .models import Department, Location, Site
from .serializers import (
    DepartmentSerializer,
    DepartmentWriteSerializer,
    LocationSerializer,
    LocationWriteSerializer,
    SiteSerializer,
    SiteWriteSerializer,
)

ReferenceDataPermission = ReadAnyWritePermission(
    (catalog.ASSETS_VIEW, catalog.SITES_MANAGE), catalog.SITES_MANAGE
)


def _if_match(request) -> int | None:
    raw = request.headers.get("If-Match")
    if raw is None:
        return None
    try:
        return int(raw.strip('"W/ '))
    except ValueError:
        return -1


def _etag(obj) -> dict:
    return {"ETag": f'"{obj.version}"'}


def visible_sites(user):
    """Site managers see every site; others only their scope."""
    if catalog.SITES_MANAGE in user.permission_codes():
        return Site.objects.all()
    return scope.restrict(Site.objects.all(), user, field="pk")


def visible_locations(user):
    return scope.restrict(Location.objects.all(), user, field="site")


# --- Sites --------------------------------------------------------------------


class SiteListCreateView(APIView):
    permission_classes = [ReferenceDataPermission]

    @extend_schema(responses=SiteSerializer(many=True))
    def get(self, request):
        return Response(SiteSerializer(visible_sites(request.user), many=True).data)

    @extend_schema(request=SiteWriteSerializer, responses={201: SiteSerializer})
    def post(self, request):
        data = SiteWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        site = services.create_site(request, data.validated_data)
        return Response(SiteSerializer(site).data, status=status.HTTP_201_CREATED)


class SiteDetailView(APIView):
    permission_classes = [ReferenceDataPermission]

    def _get(self, request, pk):
        return generics.get_object_or_404(visible_sites(request.user), pk=pk)

    @extend_schema(responses=SiteSerializer)
    def get(self, request, pk):
        site = self._get(request, pk)
        return Response(SiteSerializer(site).data, headers=_etag(site))

    @extend_schema(
        request=SiteWriteSerializer(partial=True),
        responses=SiteSerializer,
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)],
    )
    def patch(self, request, pk):
        site = self._get(request, pk)
        data = SiteWriteSerializer(site, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        site = services.update_site(request, site, data.validated_data, _if_match(request))
        return Response(SiteSerializer(site).data, headers=_etag(site))


# --- Locations ----------------------------------------------------------------


@extend_schema(parameters=[OpenApiParameter("site", str, description="Site ID")])
class LocationListCreateView(APIView):
    permission_classes = [ReferenceDataPermission]

    @extend_schema(responses=LocationSerializer(many=True))
    def get(self, request):
        qs = visible_locations(request.user)
        if site_id := request.query_params.get("site"):
            qs = qs.filter(site_id=site_id)
        return Response(LocationSerializer(qs.order_by("site__code", "name"), many=True).data)

    @extend_schema(request=LocationWriteSerializer, responses={201: LocationSerializer})
    def post(self, request):
        data = LocationWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        location = services.create_location(request, data.validated_data)
        return Response(LocationSerializer(location).data, status=status.HTTP_201_CREATED)


class LocationDetailView(APIView):
    permission_classes = [ReferenceDataPermission]

    def _get(self, request, pk):
        return generics.get_object_or_404(visible_locations(request.user), pk=pk)

    @extend_schema(responses=LocationSerializer)
    def get(self, request, pk):
        location = self._get(request, pk)
        return Response(LocationSerializer(location).data, headers=_etag(location))

    @extend_schema(
        request=LocationWriteSerializer(partial=True),
        responses=LocationSerializer,
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)],
    )
    def patch(self, request, pk):
        location = self._get(request, pk)
        data = LocationWriteSerializer(location, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        location = services.update_location(
            request, location, data.validated_data, _if_match(request)
        )
        return Response(LocationSerializer(location).data, headers=_etag(location))


# --- Departments --------------------------------------------------------------


class DepartmentListCreateView(APIView):
    permission_classes = [ReferenceDataPermission]

    @extend_schema(responses=DepartmentSerializer(many=True))
    def get(self, request):
        return Response(DepartmentSerializer(Department.objects.all(), many=True).data)

    @extend_schema(request=DepartmentWriteSerializer, responses={201: DepartmentSerializer})
    def post(self, request):
        data = DepartmentWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        department = services.create_department(request, data.validated_data)
        return Response(DepartmentSerializer(department).data, status=status.HTTP_201_CREATED)


class DepartmentDetailView(APIView):
    permission_classes = [ReferenceDataPermission]

    @extend_schema(responses=DepartmentSerializer)
    def get(self, request, pk):
        department = generics.get_object_or_404(Department, pk=pk)
        return Response(DepartmentSerializer(department).data, headers=_etag(department))

    @extend_schema(
        request=DepartmentWriteSerializer(partial=True),
        responses=DepartmentSerializer,
        parameters=[OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)],
    )
    def patch(self, request, pk):
        department = generics.get_object_or_404(Department, pk=pk)
        data = DepartmentWriteSerializer(department, data=request.data, partial=True)
        data.is_valid(raise_exception=True)
        department = services.update_department(
            request, department, data.validated_data, _if_match(request)
        )
        return Response(DepartmentSerializer(department).data, headers=_etag(department))
