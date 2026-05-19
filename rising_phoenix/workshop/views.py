from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib import messages
from django.conf import settings
from django.db import transaction
from account.models import ArtisanProfile
from rising_phoenix.moderation import image_is_clean, text_is_clean
from .models import WorkshopProfile, PortfolioImage, CompletedProject, CompletedProjectImage
from .forms import WorkshopProfileForm, PortfolioImageForm, CompletedProjectForm, ProjectImageUploadForm
from .forms import WorkshopDetailForm
from django.db.models import Q
from .models import Category
from request.models import Request
from proposal.models import Proposal
from django.core.paginator import Paginator
from progress.models import Contract


def _validate_workshop_image(image):
    """
    Returns None if the image passes all checks, or an error string if rejected.
    Checks: file size, content type, nudity.
    """
    max_size_bytes = int(float(getattr(settings, 'REQUEST_IMAGE_MAX_SIZE_MB', 5)) * 1024 * 1024)
    allowed_types = list(getattr(settings, 'REQUEST_IMAGE_ALLOWED_TYPES', ['image/jpeg', 'image/png', 'image/webp', 'image/gif']))
    if image.size > max_size_bytes:
        return f'"{image.name}" exceeds the 5 MB size limit.'
    if (getattr(image, 'content_type', '') or '').lower() not in allowed_types:
        return f'"{image.name}" is not an accepted image type (JPEG, PNG, WebP, GIF).'
    if not image_is_clean(image):
        return f'"{image.name}" was removed: explicit content detected.'
    return None


def is_artisan(user):
    """Check if user is an artisan."""
    return user.groups.filter(name='artisan').exists()


@login_required(login_url='account:login_view')
@user_passes_test(is_artisan, login_url='main:home_view')
def create_workshop_view(request):
    """Create or edit workshop profile for artisan."""
    try:
        artisan_profile = ArtisanProfile.objects.get(user=request.user)
    except ArtisanProfile.DoesNotExist:
        messages.error(request, "You must have an artisan profile to create a workshop.")
        return redirect('main:home_view')
    
    # Check if workshop already exists
    try:
        workshop = WorkshopProfile.objects.get(artisan=artisan_profile)
    except WorkshopProfile.DoesNotExist:
        workshop = None
    
    if request.method == 'POST':
        form = WorkshopProfileForm(request.POST, request.FILES, instance=workshop)
        if form.is_valid():
            with transaction.atomic():
                workshop_profile = form.save(commit=False)
                if not workshop:
                    workshop_profile.artisan = artisan_profile
                workshop_profile.save()
                # Save ManyToMany fields (categories)
                form.save_m2m()
                messages.success(request, "Workshop profile saved successfully!")
                return redirect('workshop:workshop_detail_view', artisan_id=artisan_profile.user.id)
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = WorkshopProfileForm(instance=workshop)
    
    context = {
        'form': form,
        'is_edit': workshop is not None,
        'workshop': workshop,
    }
    return render(request, 'workshop/create_workshop.html', context)



def workshop_detail_view(request, artisan_id):
    """View public workshop profile."""

    try:
        artisan_profile = ArtisanProfile.objects.get(
            user_id=artisan_id
        )

        workshop = WorkshopProfile.objects.get(
            artisan=artisan_profile
        )

    except ArtisanProfile.DoesNotExist:

        messages.error(
            request,
            "Artisan profile not found."
        )

        return redirect(
            'main:home_view'
        )

    except WorkshopProfile.DoesNotExist:

        if (
            request.user.is_authenticated
            and request.user.id == artisan_id
        ):

            messages.info(
                request,
                "You don't have a workshop yet — create one to show your profile."
            )

            return redirect(
                'workshop:create_workshop_view'
            )

        messages.error(
            request,
            "Workshop profile not found."
        )

        return redirect(
            'main:home_view'
        )

    can_edit_portfolio = (
        request.user.is_authenticated
        and request.user == artisan_profile.user
    )

    # ensure workshop details exist for display/edit
    try:
        workshop_details = workshop.details
    except Exception:
        workshop_details = None
    # prepare edit form for modal if artisan
    detail_form = WorkshopDetailForm(instance=workshop_details) if can_edit_portfolio else None


    if request.method == 'POST' and can_edit_portfolio:

        if 'toggle_pin_image_id' in request.POST:

            image_id = request.POST.get(
                'toggle_pin_image_id'
            )

            portfolio_image = (
                workshop.portfolio_images.filter(
                    id=image_id
                ).first()
            )

            if portfolio_image:

                portfolio_image.is_pinned = not portfolio_image.is_pinned

                portfolio_image.save(
                    update_fields=['is_pinned']
                )

                messages.success(
                    request,
                    f"Image {'pinned' if portfolio_image.is_pinned else 'unpinned'} successfully."
                )

            else:

                messages.error(
                    request,
                    "Portfolio image not found."
                )

            return redirect(
                'workshop:workshop_detail_view',
                artisan_id=artisan_id
            )

        if (
            'caption' in request.POST
            and 'portfolio_image_id' in request.POST
        ):

            image_id = request.POST.get(
                'portfolio_image_id'
            )

            caption = request.POST.get(
                'caption',
                ''
            ).strip()

            portfolio_image = (
                workshop.portfolio_images.filter(
                    id=image_id
                ).first()
            )

            if portfolio_image:

                portfolio_image.caption = caption

                portfolio_image.save(
                    update_fields=['caption']
                )

                messages.success(
                    request,
                    "Portfolio description updated successfully."
                )

            else:

                messages.error(
                    request,
                    "Portfolio image not found."
                )

            return redirect(
                'workshop:workshop_detail_view',
                artisan_id=artisan_id
            )


        elif 'toggle_pin_image_id' in request.POST:

            image_id = request.POST.get(
                'toggle_pin_image_id'
            )

            portfolio_image = (
                workshop.portfolio_images.filter(
                    id=image_id
                ).first()
            )

            if portfolio_image:

                portfolio_image.is_pinned = not portfolio_image.is_pinned

                portfolio_image.save(
                    update_fields=['is_pinned']
                )

                messages.success(
                    request,
                    f"Image {'pinned' if portfolio_image.is_pinned else 'unpinned'} successfully."
                )

            else:

                messages.error(
                    request,
                    "Portfolio image not found."
                )

            return redirect(
                'workshop:workshop_detail_view',
                artisan_id=artisan_id
            )


        elif 'delete_portfolio_image_id' in request.POST:

            image_id = request.POST.get(
                'delete_portfolio_image_id'
            )

            portfolio_image = (
                workshop.portfolio_images.filter(
                    id=image_id
                ).first()
            )

            if portfolio_image:

                portfolio_image.delete()

                messages.success(
                    request,
                    "Portfolio image deleted successfully."
                )

            else:

                messages.error(
                    request,
                    "Portfolio image not found."
                )

            return redirect(
                'workshop:workshop_detail_view',
                artisan_id=artisan_id
            )

        elif 'edit_workshop_details' in request.POST:

            form = WorkshopDetailForm(request.POST, instance=getattr(workshop, 'details', None))

            if form.is_valid():
                detail = form.save(commit=False)
                detail.workshop = workshop
                detail.save()
                messages.success(request, 'Workshop details updated successfully.')
            else:
                messages.error(request, 'Please correct errors in the details form.')

            return redirect('workshop:workshop_detail_view', artisan_id=artisan_id)


    # Reviews
    reviews_list = (
        artisan_profile.user.reviews_received
        .select_related(
            'reviews_given',
            'request'
        )
        .order_by(
            '-created_at'
        )
    )

    paginator = Paginator(
        reviews_list,
        6
    )

    page_number = request.GET.get(
        'review_page'
    )

    reviews = paginator.get_page(
        page_number
    )


    # Closed requests linked to this artisan (same logic as account completed-orders page)
    completed_orders_qs = (
        Request.objects.filter(
            status=Request.Status.CLOSED,
            proposals__artisan=artisan_profile.user,
            proposals__status=Proposal.Status.ACCEPTED,
        )
        .distinct()
        .order_by('-created_at')
    )

    closed_paginator = Paginator(
        completed_orders_qs,
        6
    )

    closed_page_number = request.GET.get(
        'closed_page'
    )

    completed_orders = closed_paginator.get_page(
        closed_page_number
    )

    completed_orders_count = completed_orders.paginator.count

    active_orders_count = Contract.objects.filter(
        proposal__artisan=artisan_profile.user,
        status=Contract.Status.IN_PROGRESS,
    ).count()


    portfolio_qs = workshop.portfolio_images.all()

    portfolio_paginator = Paginator(
        portfolio_qs,
        6
    )

    portfolio_page_number = request.GET.get(
        'portfolio_page'
    )

    portfolio_images = portfolio_paginator.get_page(
        portfolio_page_number
    )

    is_viewer_artisan = (
        request.user.is_authenticated
        and request.user.groups.filter(name='artisan').exists()
    )

    context = {

        'workshop': workshop,
        'artisan': artisan_profile,

        'portfolio_images':
        portfolio_images,
        'portfolio_images_count':
        portfolio_images.paginator.count,

        'can_edit_portfolio':
        can_edit_portfolio,

        'reviews': reviews,

        'completed_orders':
        completed_orders,
        'completed_orders_count':
        completed_orders_count,
        'active_orders_count':
        active_orders_count,
        'workshop_details': workshop_details,
        'detail_form': detail_form,

        'is_viewer_artisan': is_viewer_artisan,

    }

    return render(
        request,
        'workshop/workshop_detail.html',
        context
    )


def portfolio_list_view(request, artisan_id):
    """List all portfolio images for an artisan workshop."""

    try:
        artisan_profile = ArtisanProfile.objects.get(
            user_id=artisan_id
        )

        workshop = WorkshopProfile.objects.get(
            artisan=artisan_profile
        )

    except ArtisanProfile.DoesNotExist:

        messages.error(
            request,
            "Artisan profile not found."
        )

        return redirect(
            'main:home_view'
        )

    except WorkshopProfile.DoesNotExist:

        messages.error(
            request,
            "Workshop profile not found."
        )

        return redirect(
            'main:home_view'
        )

    can_edit_portfolio = (
        request.user.is_authenticated
        and request.user == artisan_profile.user
    )

    if request.method == 'POST' and can_edit_portfolio:

        if 'toggle_pin_image_id' in request.POST:

            image_id = request.POST.get(
                'toggle_pin_image_id'
            )

            portfolio_image = (
                workshop.portfolio_images.filter(
                    id=image_id
                ).first()
            )

            if portfolio_image:

                portfolio_image.is_pinned = not portfolio_image.is_pinned

                portfolio_image.save(
                    update_fields=['is_pinned']
                )

                messages.success(
                    request,
                    f"Image {'pinned' if portfolio_image.is_pinned else 'unpinned'} successfully."
                )

            else:

                messages.error(
                    request,
                    "Portfolio image not found."
                )

            return redirect(
                'workshop:portfolio_list_view',
                artisan_id=artisan_id
            )

        if 'delete_portfolio_image_id' in request.POST:

            image_id = request.POST.get(
                'delete_portfolio_image_id'
            )

            portfolio_image = (
                workshop.portfolio_images.filter(
                    id=image_id
                ).first()
            )

            if portfolio_image:

                portfolio_image.delete()

                messages.success(
                    request,
                    "Portfolio image deleted successfully."
                )

            else:

                messages.error(
                    request,
                    "Portfolio image not found."
                )

            return redirect(
                'workshop:portfolio_list_view',
                artisan_id=artisan_id
            )

    paginator = Paginator(
        workshop.portfolio_images.all(),
        6
    )

    page_number = request.GET.get(
        'page'
    )

    page_obj = paginator.get_page(
        page_number
    )

    context = {
        'workshop': workshop,
        'artisan': artisan_profile,
        'portfolio_images': page_obj,
        'page_obj': page_obj,
        'can_edit_portfolio': can_edit_portfolio,
    }

    return render(
        request,
        'workshop/portfolio_list.html',
        context
    )


@login_required(login_url='account:login_view')
@user_passes_test(is_artisan, login_url='main:home_view')
def upload_portfolio_view(request):
    """Upload portfolio images for an artisan workshop."""
    try:
        artisan_profile = ArtisanProfile.objects.get(user=request.user)
        workshop = WorkshopProfile.objects.get(artisan=artisan_profile)
    except ArtisanProfile.DoesNotExist:
        messages.error(request, "You must have an artisan profile to upload portfolio images.")
        return redirect('main:home_view')
    except WorkshopProfile.DoesNotExist:
        messages.error(request, "You must create a workshop profile first.")
        return redirect('workshop:create_workshop_view')

    if request.method == 'POST':
        if 'update_caption_image_id' in request.POST:
            image_id = request.POST.get('update_caption_image_id')
            new_caption = request.POST.get('caption', '').strip()
            portfolio_image = workshop.portfolio_images.filter(id=image_id).first()

            if not portfolio_image:
                messages.error(request, 'Portfolio image not found.')
                return redirect('workshop:upload_portfolio_view')

            if new_caption and not text_is_clean(new_caption):
                messages.error(request, 'Caption contains inappropriate language. Please revise it.')
                return redirect('workshop:upload_portfolio_view')

            portfolio_image.caption = new_caption
            portfolio_image.save(update_fields=['caption'])
            messages.success(request, 'Image caption updated successfully.')
            return redirect('workshop:upload_portfolio_view')

        if 'delete_image_id' in request.POST:
            image_id = request.POST.get('delete_image_id')
            portfolio_image = workshop.portfolio_images.filter(id=image_id).first()
            if portfolio_image:
                portfolio_image.delete()
                messages.success(request, 'Portfolio image deleted successfully.')
            else:
                messages.error(request, 'Portfolio image not found.')
            return redirect('workshop:upload_portfolio_view')

        if 'toggle_pin_image_id' in request.POST:
            image_id = request.POST.get('toggle_pin_image_id')
            portfolio_image = workshop.portfolio_images.filter(id=image_id).first()
            if portfolio_image:
                portfolio_image.is_pinned = not portfolio_image.is_pinned
                portfolio_image.save(update_fields=['is_pinned'])
                messages.success(request, f"Image {'pinned' if portfolio_image.is_pinned else 'unpinned'} successfully.")
            else:
                messages.error(request, "Portfolio image not found.")
            return redirect('workshop:upload_portfolio_view')

        form = PortfolioImageForm(request.POST, request.FILES)

        if form.is_valid():
            images = form.cleaned_data['images']
            caption = form.cleaned_data.get('caption', '')
            is_pinned = form.cleaned_data.get('is_pinned', False)

            if not images:
                messages.error(request, "Please select at least one image to upload.")
            else:
                if caption and not text_is_clean(caption):
                    caption = ''
                saved_count = 0
                with transaction.atomic():
                    for image in images:
                        error = _validate_workshop_image(image)
                        if error:
                            messages.warning(request, f'Image skipped: {error}')
                            continue
                        PortfolioImage.objects.create(
                            workshop=workshop,
                            image=image,
                            caption=caption,
                            is_pinned=is_pinned,
                        )
                        saved_count += 1

                if saved_count:
                    messages.success(request, f"{saved_count} portfolio image(s) uploaded successfully.")
                return redirect('workshop:upload_portfolio_view')
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = PortfolioImageForm()

    context = {
        'form': form,
        'workshop': workshop,
        'portfolio_images': workshop.portfolio_images.all(),
    }
    return render(request, 'workshop/upload_portfolio.html', context)

# Create your views here.


@login_required(login_url='account:login_view')
@user_passes_test(is_artisan, login_url='main:home_view')
def create_project_view(request):
    """Create a completed project entry for the artisan's workshop."""
    try:
        artisan_profile = ArtisanProfile.objects.get(user=request.user)
        workshop = WorkshopProfile.objects.get(artisan=artisan_profile)
    except (ArtisanProfile.DoesNotExist, WorkshopProfile.DoesNotExist):
        messages.error(request, "You must create a workshop profile first.")
        return redirect('workshop:create_workshop_view')

    if request.method == 'POST':
        form = CompletedProjectForm(request.POST, request.FILES)
        # restrict request choices to accepted proposals by this artisan
        form.fields['request'].queryset = Request.objects.filter(proposals__artisan=request.user, proposals__status=Proposal.Status.ACCEPTED).distinct()
        
        if form.is_valid():
            project = form.save(commit=False)
            project.workshop = workshop
            project.save()
            messages.success(request, "Completed project created. You can now upload project images.")
            return redirect('workshop:upload_project_images_view', project_id=project.id)
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = CompletedProjectForm()
        form.fields['request'].queryset = Request.objects.filter(proposals__artisan=request.user, proposals__status=Proposal.Status.ACCEPTED).distinct()

    return render(request, 'workshop/create_project.html', {'form': form, 'workshop': workshop})


@login_required(login_url='account:login_view')
@user_passes_test(is_artisan, login_url='main:home_view')
def upload_project_images_view(request, project_id):
    """Upload images for a completed project."""
    try:
        project = CompletedProject.objects.get(id=project_id)
        artisan_profile = ArtisanProfile.objects.get(user=request.user)
        # ensure project belongs to this artisan
        if project.workshop.artisan != artisan_profile:
            messages.error(request, "You don't have permission to edit this project.")
            return redirect('workshop:workshop_detail_view', artisan_id=request.user.id)
    except CompletedProject.DoesNotExist:
        messages.error(request, "Project not found.")
        return redirect('main:home_view')
    except ArtisanProfile.DoesNotExist:
        messages.error(request, "Artisan profile not found.")
        return redirect('main:home_view')

    if request.method == 'POST':
        form = ProjectImageUploadForm(request.POST, request.FILES)
        if form.is_valid():
            images = form.cleaned_data['images']
            caption = form.cleaned_data.get('caption', '')
            is_before = form.cleaned_data.get('is_before', False)

            if not images:
                messages.error(request, "Please select at least one image to upload.")
            else:
                if caption and not text_is_clean(caption):
                    caption = ''
                saved_count = 0
                with transaction.atomic():
                    for img in images:
                        error = _validate_workshop_image(img)
                        if error:
                            messages.warning(request, f'Image skipped: {error}')
                            continue
                        CompletedProjectImage.objects.create(
                            project=project,
                            image=img,
                            caption=caption,
                            is_before=is_before,
                        )
                        saved_count += 1
                if saved_count:
                    messages.success(request, f"{saved_count} project image(s) uploaded successfully.")
                return redirect('workshop:project_detail_view', project_id=project.id)
        else:
            messages.error(request, "Please correct the errors below.")
    else:
        form = ProjectImageUploadForm()

    context = {
        'form': form,
        'project': project,
        'images': project.images.all(),
    }
    return render(request, 'workshop/upload_project_images.html', context)


def project_detail_view(request, project_id):
    """Public detail view for a completed project."""
    try:
        project = CompletedProject.objects.get(id=project_id, is_published=True)
    except CompletedProject.DoesNotExist:
        messages.error(request, "Project not found or not published.")
        return redirect('main:home_view')

    # group images by pair_group for before/after display
    images = project.images.all()
    pair_groups = {}
    for img in images:
        key = img.pair_group or 0
        pair_groups.setdefault(key, []).append(img)

    context = {
        'project': project,
        'pair_groups': pair_groups,
    }
    return render(request, 'workshop/project_detail.html', context)


# def projects_list_view(request, artisan_id):
#     """List all published completed projects for an artisan's workshop."""
#     try:
#         artisan_profile = ArtisanProfile.objects.get(user_id=artisan_id)
#         workshop = WorkshopProfile.objects.get(artisan=artisan_profile)
#     except (ArtisanProfile.DoesNotExist, WorkshopProfile.DoesNotExist):
#         messages.error(request, "Workshop not found.")
#         return redirect('main:home_view')

#     projects = workshop.completed_projects.filter(is_published=True).order_by('-is_featured', '-date_completed')

#     return render(request, 'workshop/projects_list.html', {'workshop': workshop, 'projects': projects, 'artisan': artisan_profile})
def projects_list_view(request, artisan_id):
    """List all published completed projects for an artisan's workshop."""

    try:
        artisan_profile = ArtisanProfile.objects.get(user_id=artisan_id)
        workshop = WorkshopProfile.objects.get(artisan=artisan_profile)

    except (ArtisanProfile.DoesNotExist, WorkshopProfile.DoesNotExist):
        messages.error(request, "Workshop not found.")
        return redirect('main:home_view')

    projects = workshop.completed_projects.filter(
        is_published=True
    ).prefetch_related(
        'images',
        'request'
    ).order_by(
        '-is_featured',
        '-date_completed'
    )

    context = {
        'workshop': workshop,
        'projects': projects,
        'artisan': artisan_profile,
    }

    return render(
        request,
        'workshop/projects_list.html',
        context
    )


def artisans_list_view(request):
    """Browse and search artisan workshop profiles."""
    q = request.GET.get('q', '').strip()
    category_id = request.GET.get('category')

    qs = WorkshopProfile.objects.filter(is_published=True).select_related('artisan__user').prefetch_related('categories')

    if category_id:
        try:
            qs = qs.filter(categories__id=int(category_id))
        except (ValueError, TypeError):
            pass

    if q:
        qs = qs.filter(
            Q(workshop_name__icontains=q) |
            Q(tagline__icontains=q) |
            Q(description__icontains=q) |
            Q(services__icontains=q) |
            Q(location__icontains=q) |
            Q(artisan__user__first_name__icontains=q) |
            Q(artisan__user__last_name__icontains=q)
        )

    qs = qs.distinct().order_by('-is_published', '-updated_at')

    categories = Category.objects.all().order_by('name')

    context = {
        'workshops': qs,
        'categories': categories,
        'q': q,
        'selected_category': int(category_id) if category_id and category_id.isdigit() else None,
    }
    return render(request, 'workshop/artisans_list.html', context)
