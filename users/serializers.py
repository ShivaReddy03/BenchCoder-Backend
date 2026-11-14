from rest_framework import serializers
from .models import User
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db.models import Sum


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=6)

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'password')

    def validate(self, attrs):
        user = User(username=attrs.get("username", ""), email=attrs.get("email", ""))
        try:
            validate_password(attrs["password"], user=user)
        except ValidationError as exc:
            raise serializers.ValidationError({"password": list(exc.messages)})
        return attrs

    def create(self, validated_data):
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password'],
        )
        return user


class UserLoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField()

    def validate(self, attrs):
        username = attrs.get('username')
        password = attrs.get('password')

        if username and password:
            user = authenticate(username=username, password=password)

            if user:
                if not user.is_active:
                    raise serializers.ValidationError("User account is disabled.")
                attrs['user'] = user
                return attrs
            raise serializers.ValidationError("Unable to log in with provided credentials.")

        raise serializers.ValidationError("Must include 'username' and 'password'.")


class UserProfileSerializer(serializers.ModelSerializer):
    score = serializers.SerializerMethodField()
    problems_solved = serializers.SerializerMethodField()

    def _solve_stats(self, obj):
        # The solve ledger is authoritative when admins change or delete problems.
        # Cache only within this serializer response, never across requests.
        if not hasattr(self, '_stats'):
            self._stats = {}
        if obj.pk not in self._stats:
            from submissions.models import ProblemSolve
            solves = ProblemSolve.objects.filter(user=obj)
            self._stats[obj.pk] = (solves.aggregate(score=Sum('problem__points'))['score'] or 0, solves.count())
        return self._stats[obj.pk]

    def get_score(self, obj):
        return self._solve_stats(obj)[0]

    def get_problems_solved(self, obj):
        return self._solve_stats(obj)[1]

    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'score', 'problems_solved', 'is_staff')
