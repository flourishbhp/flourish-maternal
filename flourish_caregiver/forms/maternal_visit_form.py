from django import forms
from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from edc_action_item.site_action_items import site_action_items
from edc_constants.constants import PARTICIPANT, ALIVE, NO, FAILED_ELIGIBILITY
from edc_constants.constants import OFF_STUDY, DEAD, YES, ON_STUDY, NEW, OTHER
from edc_base.sites import SiteModelFormMixin
from edc_form_validators import FormValidatorMixin
from edc_visit_tracking.constants import COMPLETED_PROTOCOL_VISIT
from edc_visit_tracking.constants import LOST_VISIT, SCHEDULED, MISSED_VISIT
from edc_visit_tracking.form_validators import VisitFormValidator

from flourish_prn.action_items import CAREGIVEROFF_STUDY_ACTION
from flourish_form_validations.form_validators.form_validator_mixin import (
    FlourishFormValidatorMixin)

from ..models import MaternalVisit


class MaternalVisitFormValidator(VisitFormValidator, FlourishFormValidatorMixin):

    def clean(self):
        super().clean()

        self.subject_identifier = self.cleaned_data.get(
            'appointment').subject_identifier
        id = None
        if self.instance:
            id = self.instance.id
            if not id:
                self.validate_offstudy_model()

        self.validate_against_consent_datetime(self.cleaned_data.get('report_datetime'))

        self.validate_study_status()

        self.validate_lost_to_fu()

        self.validate_death()

        self.validate_is_present()

        self.validate_last_alive_date(id=id)

    def validate_data_collection(self):
        if (self.cleaned_data.get('reason') == SCHEDULED
                and self.cleaned_data.get('study_status') == ON_STUDY
                and self.cleaned_data.get('require_crfs') == NO):
            msg = {'require_crfs': 'This field must be yes if participant'
                   'is on study and present.'}
            self._errors.update(msg)
            raise ValidationError(msg)

    def validate_offstudy_model(self):
        maternal_offstudy_cls = django_apps.get_model('flourish_prn.caregiveroffstudy')
        action_cls = site_action_items.get(
            maternal_offstudy_cls.action_name)
        action_item_model_cls = action_cls.action_item_model_cls()

        try:
            action_item_model_cls.objects.get(
                subject_identifier=self.subject_identifier,
                action_type__name=CAREGIVEROFF_STUDY_ACTION,
                status=NEW)
        except action_item_model_cls.DoesNotExist:
            try:
                maternal_offstudy_cls.objects.get(
                    subject_identifier=self.subject_identifier)
            except maternal_offstudy_cls.DoesNotExist:
                pass
            else:
                raise forms.ValidationError(
                    'Participant has been taken offstudy. Cannot capture any '
                    'new data.')
        else:
            self.maternal_visit = self.cleaned_data.get('maternal_visit') or None
            if not self.maternal_visit or self.maternal_visit.require_crfs == NO:
                raise forms.ValidationError(
                    'Participant is scheduled to be taken offstudy without '
                    'any new data collection. Cannot capture any new data.')

    def validate_lost_to_fu(self):

        reason = self.cleaned_data.get('reason')

        if (reason == LOST_VISIT and
                self.cleaned_data.get('info_source') == 'other_contact'):
            msg = {'info_source': 'Source of information cannot be other contact with '
                   'participant if participant has been lost to follow up.'}
            self._errors.update(msg)
            raise ValidationError(msg)

    def validate_is_present(self):

        reason = self.cleaned_data.get('reason')

        if (reason == LOST_VISIT and
                self.cleaned_data.get('study_status') != OFF_STUDY):
            msg = {'study_status': 'Participant has been lost to follow up, '
                   'study status should be off study.'}
            self._errors.update(msg)
            raise ValidationError(msg)

        if (reason == COMPLETED_PROTOCOL_VISIT and
                self.cleaned_data.get('study_status') != OFF_STUDY):
            msg = {'study_status': 'Participant is completing protocol, '
                   'study status should be off study.'}
            self._errors.update(msg)
            raise ValidationError(msg)

        if reason == SCHEDULED and self.cleaned_data.get('study_status') == OFF_STUDY:
            msg = {'study_status': 'Participant\'s study status is offstudy, '
                   'reason for visit can not be scheduled.'}
            self._errors.update(msg)
            raise ValidationError(msg)

        if self.cleaned_data.get('is_present') == YES:
            if self.cleaned_data.get('info_source') != PARTICIPANT:
                raise forms.ValidationError(
                    {'info_source': 'Source of information must be from '
                     'participant if participant is present.'})

    def validate_death(self):
        if (self.cleaned_data.get('survival_status') == DEAD
                and self.cleaned_data.get('study_status') != OFF_STUDY):
            msg = {'study_status': 'Participant is deceased, study status '
                   'should be off study.'}
            self._errors.update(msg)
            raise ValidationError(msg)
        if self.cleaned_data.get('survival_status') != ALIVE:
            if (self.cleaned_data.get('is_present') == YES
                    or self.cleaned_data.get('info_source') == PARTICIPANT):
                msg = {'survival_status': 'Participant cannot be present or '
                       'source of information if their survival status is not'
                       'alive.'}
                self._errors.update(msg)
                raise ValidationError(msg)

    def validate_last_alive_date(self, id=None):
        """Returns an instance of the current maternal consent or
        raises an exception if not found."""

        latest_consent = self.validate_against_consent()
        last_alive_date = self.cleaned_data.get('last_alive_date')
        if (last_alive_date
                and last_alive_date < latest_consent.consent_datetime.date()):
            msg = {'last_alive_date': 'Date cannot be before consent date'}
            self._errors.update(msg)
            raise ValidationError(msg)

    def validate_reason_and_info_source(self):
        pass

    def validate_study_status(self):
        maternal_offstudy_cls = django_apps.get_model(
            'flourish_prn.caregiveroffstudy')
        action_cls = site_action_items.get(
            maternal_offstudy_cls.action_name)
        action_item_model_cls = action_cls.action_item_model_cls()

        try:
            action_item = action_item_model_cls.objects.get(
                subject_identifier=self.subject_identifier,
                action_type__name=CAREGIVEROFF_STUDY_ACTION,
                status=NEW)
        except action_item_model_cls.DoesNotExist:
            try:
                maternal_offstudy_cls.objects.get(
                    subject_identifier=self.subject_identifier)
            except maternal_offstudy_cls.DoesNotExist:
                pass
            else:
                if self.cleaned_data.get('study_status') == ON_STUDY:
                    raise forms.ValidationError(
                        {'study_status': 'Participant has been taken offstudy.'
                         ' Cannot be indicated as on study.'})
        else:
            if (action_item.parent_reference_model_obj
                and self.cleaned_data.get(
                    'report_datetime') >= action_item.parent_reference_model_obj.report_datetime):
                raise forms.ValidationError(
                    'Participant is scheduled to go offstudy.'
                    ' Cannot edit visit until offstudy form is completed.')

        if (self.cleaned_data.get('reason') == FAILED_ELIGIBILITY
                and self.cleaned_data.get('study_status') == ON_STUDY):
            raise forms.ValidationError(
                {'study_status': 'Participant failed eligibility, they cannot be  indicated '
                 'as on study.'})

    def validate_required_fields(self):

        self.required_if(
            MISSED_VISIT,
            field='reason',
            field_required='reason_missed')

        self.required_if(
            OTHER,
            field='info_source',
            field_required='info_source_other')


class MaternalVisitForm(SiteModelFormMixin, FormValidatorMixin, forms.ModelForm):

    form_validator_cls = MaternalVisitFormValidator

    class Meta:
        model = MaternalVisit
        fields = '__all__'
